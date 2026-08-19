"""把单段 mp3,按 `script.py` 的 assemble_manifest() 拼成一整期能听的音频。

之前"不做混音"这条边界这次应你的要求又松了一格——但只到这几件事为止:
真正插入脚本里设计好的静音段、按 assemble_manifest() 算好的换人间隔插入
真实静音(而不是硬切)、同一个人连续说话时做个短交叉淡化避免分句拼接的
"一顿一顿"感、响度粗略拉平(避免两个音色忽大忽小)。不加音效、不加配乐、
不做真正的母带处理,那些仍然不在这个仓库的范围内,还是交给你现有的
ffmpeg 链路。

第一版这里自己写了一套间隔/交叉淡化逻辑,后来发现 `script.py` 里已经有
`assemble_manifest()` 专门算"间隔多少、为什么"——那份是更早一次会话做的,
这次改成直接消费它的输出,不重复造轮子。
"""

from __future__ import annotations

import os
from pathlib import Path

import static_ffmpeg
from pydub import AudioSegment

from ..models import Channel, Script
from ..script import assemble_manifest

# pydub 找 ffmpeg/ffprobe 只认 PATH(get_prober_name()/get_encoder_name() 是
# which() 查找,不读 AudioSegment.converter 之外的属性),所以把 static-ffmpeg
# 下载好的那份二进制目录塞进 PATH,而不是只设 AudioSegment 的几个属性。
_ffmpeg_path, _ffprobe_path = static_ffmpeg.run.get_or_fetch_platform_executables_else_raise()
_bin_dir = str(Path(_ffmpeg_path).parent)
if _bin_dir not in os.environ.get("PATH", ""):
    os.environ["PATH"] = _bin_dir + os.pathsep + os.environ.get("PATH", "")
AudioSegment.converter = _ffmpeg_path

SAME_VOICE_CROSSFADE_MS = 60  # 同一个人连续说话,做个很轻的淡化避免分句接缝的"咔"声
TARGET_DBFS = -18.0


def _match_loudness(seg: AudioSegment) -> AudioSegment:
    if seg.dBFS == float("-inf"):
        return seg
    return seg.apply_gain(TARGET_DBFS - seg.dBFS)


def stitch_script(script: Script, ch: Channel, tts_dir: Path, out_path: Path) -> Path:
    """script:已加载的 Script。ch:所属频道(assemble_manifest 要用它算间隔)。
    tts_dir:`rf synthesize` 的输出目录(文件名规则 `seg_{index:02d}_{kind}.mp3`)。
    out_path:输出的整期 mp3。"""
    manifest = assemble_manifest(script, ch)

    track: AudioSegment | None = None
    for m in manifest:
        if m["type"] == "silence":
            piece = AudioSegment.silent(duration=int(m["seconds"] * 1000))
            gap_ms, reason = 0, "is_silence"
        elif m["type"] == "tts":
            path = tts_dir / m["source"]
            if not path.exists():
                continue
            piece = _match_loudness(AudioSegment.from_file(path, format="mp3"))
            gap_ms, reason = m["gap_before_ms"], m["gap_reason"]
        else:
            # type == "asset"(sting/sfx) —— 目前没有把音效/台呼渲染进采样,跳过
            continue

        if track is None:
            track = piece
            continue

        if gap_ms > 0:
            track = track + AudioSegment.silent(duration=gap_ms) + piece
        elif reason == "same_voice" and len(piece) >= SAME_VOICE_CROSSFADE_MS and len(track) >= SAME_VOICE_CROSSFADE_MS:
            track = track.append(piece, crossfade=SAME_VOICE_CROSSFADE_MS)
        else:
            track = track + piece

    if track is None:
        raise ValueError("没有可拼接的音频,先跑 rf synthesize 生成分段")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    track.export(out_path, format="mp3", bitrate="128k")
    return out_path
