# v2srt - 视频智能字幕生成工具

v2srt 是一个基于人工智能的视频字幕生成工具，能够快速、准确地为任意视频文件生成高质量的字幕文件。

## ✨ 功能特点

- **🎯 本地运行**: 使用 [whisper.cpp](https://github.com/ggerganov/whisper.cpp) 在本地运行 Whisper 模型生成字幕，无需依赖云服务
- **⚡ GPU 加速**: 支持使用 GPU 运行模型，大幅提升字幕生成速度
- **🌐 智能翻译**: 集成 Gemini API，支持将生成的字幕自动翻译成中文（可选）
- **🎙️ 人声检测**: 使用 Silero VAD 模型进行人声活动检测，提高字幕准确性（可选）
- **📝 多格式支持**: 支持大多数视频格式，并输出标准 SRT 格式字幕文件
- **🔧 灵活配置**: 支持自定义语言、模型选择和时间分段处理

## 📋 系统要求

- Python 3.12+
- FFmpeg（用于音视频处理）
- whisper.cpp（Whisper C++实现）

### 依赖安装

```bash
pip install -r requirements.txt
```

## 🚀 快速开始

### 基本用法

指定Whisper模型和视频文件路径，即可为视频生成其对应语言的字幕文件：

```bash
python v2srt.py -wm path/to/whisper_model.bin /path/to/your_video.mp4
```

### 手工指定语言

使用`-l`参数可以手工指定音频语言，默认情况下会自动检测音频语言：

```bash
python v2srt.py -wm path/to/whisper_model.bin \
    -l ja \
    /path/to/your_video.mp4
```

### 带翻译功能

指定Gemini模型和API密钥，将可以将字幕文件自动翻译成中文：

```bash
python v2srt.py -wm path/to/whisper_model.bin \
    -gm gemini-2.5-flash-preview-05-20 \
    -gk your_gemini_api_key \
    -l ja \
    /path/to/your_video.mp4
```

### 使用VAD模型提高准确性

```bash
python v2srt.py -wm path/to/whisper_model.bin \
    -vm path/to/vad_model.bin \
    -gm gemini-2.5-flash-preview-05-20 \
    -gk your_gemini_api_key \
    -l ja \
    /path/to/your_video.mp4
```

### 分段处理长视频

当视频过长时，模型识别效果将会下降。你可以通过`-c`参数指定视频分段时间点，将视频分段处理：

```bash
python v2srt.py -wm path/to/whisper_model.bin \
    -vm path/to/vad_model.bin \
    -gm gemini-2.5-flash-preview-05-20 \
    -gk your_gemini_api_key \
    -c 01:00:00 02:00:00 \
    -l ja \
    /path/to/your_video.mp4
```

假如视频长度是3个小时，上述命令将会在第1小时和第2小时处对视频进行切割，并为三个子视频逐一生成字幕，最终再将字幕合并，这个过程不会修改原始视频。

## 📖 详细参数说明

| 参数 | 简写 | 必需 | 说明 |
|------|------|------|------|
| `input_file` | - | ✅ | 输入视频文件路径 |
| `--model` | `-wm` | ✅ | Whisper.cpp 模型文件路径 |
| `--vad-model` | `-vm` | ❌ | VAD 模型文件路径（可以提高识别准确性，不指定则不使用） |
| `--gemini-model` | `-gm` | ❌ | Gemini 模型名称（默认：gemini-2.5-flash-preview-05-20） |
| `--gemini-key` | `-gk` | ❌ | Gemini API 密钥（用于翻译，不指定则不进行翻译） |
| `--language` | `-l` | ❌ | 音频语言（默认：auto，自动识别音频语言） |
| `--cut-times` | `-c` | ❌ | 视频分段时间点（格式：HH:MM:SS） |
| `--output` | `-o` | ❌ | 输出文件名（默认：原文件名.srt） |

## 🔧 运行前准备

### 安装 FFmpeg

从 [FFmpeg releases](https://ffmpeg.org/download.html) 可以下载 FFmpeg 的二进制文件，并添加到系统 PATH 环境变量中。

### Whisper 命令行程序

从 [whisper.cpp releases](https://github.com/ggerganov/whisper.cpp/releases) 可以下载 Whisper.cpp 的二进制文件，并添加到系统 PATH 环境变量中。

### Whisper 模型

你可以在[ggerganov/whisper.cpp](https://huggingface.co/ggerganov/whisper.cpp/tree/main)下载预训练模型，推荐选择下面三个系列，如果显卡性能较好可以选择large：

- `ggml-small.bin` - 速度较快，准确性一般
- `ggml-medium.bin` - 速度较慢，准确性较高
- `ggml-large.bin` - 速度最慢，准确性最高

### VAD 模型

从 [ggml-org/whisper-vad](https://huggingface.co/ggml-org/whisper-vad/tree/main) 获取 Silero VAD 模型文件。

## 🌐 翻译功能

v2srt 支持使用 Google Gemini API 进行智能翻译：

1. 获取 Gemini API 密钥：访问 [Google AI Studio](https://aistudio.google.com/apikey)
2. 在命令行中使用 `-gk` 参数提供API密钥
3. 程序会自动将识别出的文本翻译成中文

### 使用代理访问 Gemini API

对于中国大陆用户，如果无法直接访问 Gemini API，可以通过设置代理来解决：

比如：

```bash
# Windows
set GRPC_PROXY=http://127.0.0.1:1080
python v2srt.py -wm path/to/whisper_model.bin -gk your_gemini_api_key /path/to/your_video.mp4

# Linux/Mac
export GRPC_PROXY=http://127.0.0.1:1080
python v2srt.py -wm path/to/whisper_model.bin -gk your_gemini_api_key /path/to/your_video.mp4
```

或者：

```bash
GRPC_PROXY=http://127.0.0.1:1080 python v2srt.py -wm path/to/whisper_model.bin -gk your_gemini_api_key /path/to/your_video.mp4
```

## ⚠️ 注意事项

- 将 FFmpeg、Whisper.cpp 的二进制文件添加到系统 PATH 环境变量中
- Gemini API 可能产生费用，请注意使用量
- VAD 模型可以提高识别准确性，但会增加处理时间
- 超过1个小时的视频，建议使用`-c`参数进行分段处理

## 📄 许可证

[MIT](https://opensource.org/licenses/MIT)

---

**🎉 享受智能字幕生成的便利！** 