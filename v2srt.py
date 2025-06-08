import json
import os
import argparse
import logging
import shutil
import subprocess
import tempfile
import atexit
import sys
import re
from typing import Union, List, Iterable, Tuple, Mapping
from itertools import pairwise, batched
from google import genai
from google.genai import types

logging.basicConfig(stream=sys.stdout, level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
seconds_pattern = re.compile(r'\d{2}:\d{2}:\d{2},\d{3}')
seconds_with_milliseconds_pattern = re.compile(r'\d{2}:\d{2}:\d{2}')
default_gemini_model = 'gemini-2.5-flash-preview-05-20'


class VideoHandler(object):
    def __init__(self, whisper_model: str, gemini_model: str = default_gemini_model, gemini_api_key: str = '',
                 vad_model: str = '', language: str = 'auto', cut_times: 'List[TimeCode]' = None):
        self.whisper_model = whisper_model
        self.gemini_model = gemini_model
        self.vad_model = vad_model
        self.language = language
        self.cut_times = cut_times or []
        self.base_path = tempfile.mkdtemp(prefix='v2srt')
        self.translate_threshold = 50
        if gemini_api_key:
            self.gemini_client = genai.Client(api_key=gemini_api_key)
        else:
            self.gemini_client = None
        atexit.register(self.cleanup)
        logging.info("base working directory: %s", self.base_path)

    def run(self, video_path: str, output_path: str):
        wav_path = self.video_to_wav(video_path)
        logging.info("wav file path: %s", wav_path)
        with open(output_path, 'w', encoding='utf-8') as fout:
            base = 1
            for base_time, cut_wav_path in self.cut_wav(wav_path):
                logging.info("cut wav base time: %s, file path: %s", str(base_time), cut_wav_path)
                transcription_path = self.generate_transcription(cut_wav_path)
                logging.info("transcription file path: %s", transcription_path)

                with open(transcription_path, 'rb') as fin:
                    data = json.load(fin)

                for batch in batched(data['transcription'], self.translate_threshold):
                    logging.info("start to translate from No.%d to No.%d", base, base+len(batch)-1)
                    entries = {base+i: SRTEntry(index=base+i, start_time=entry['timestamps']['from'],
                                        end_time=entry['timestamps']['to'], text=entry["text"]) for i, entry in enumerate(batch)}
                    base += len(batch)

                    if self.gemini_client:
                        self.translate_batch(entries)

                    for entry in entries.values():
                        fout.write(str(entry))

                fout.flush()

    def video_to_wav(self, video_path: str) -> str:
        _, name = os.path.split(video_path)
        basename, ext = os.path.splitext(name)
        wav_file = os.path.join(self.base_path, basename + ".wav")
        logging.info("convert video file %s to wav file %s", video_path, wav_file)
        subprocess.run(["ffmpeg", "-i", video_path, "-af", "aresample=async=1", "-ar", "16000", "-ac", "1", "-c:a",
                        "pcm_s16le", "-loglevel", "fatal", wav_file])
        return wav_file

    def cut_wav(self, wav_path: str) -> 'Iterable[Tuple[TimeCode, str]]':
        basename, ext = os.path.splitext(wav_path)
        pairs = pairwise([TimeCode('00:00:00,000'), *self.cut_times, 'end'])
        i = 1
        for start, to in pairs:
            cmd = ["ffmpeg", "-i", wav_path]
            if start.is_zero() and to == 'end':
                yield start, wav_path
                break

            cmd.extend(['-ss', start.without_millis()])
            if to != 'end':
                cmd.extend(['-to', to.without_millis()])

            output_path = f"{basename}-{i}.wav"
            i += 1
            cmd.extend(["-c", "copy", "-loglevel", "error", output_path])
            subprocess.run(cmd)
            yield start, output_path

    def generate_transcription(self, wav_path: str) -> str:
        basename, _ = os.path.splitext(wav_path)
        cmd = ["whisper-cli.exe", "-l", self.language, "-oj", "-m", self.whisper_model]
        if self.vad_model:
            cmd.extend(['--vad', '--vad-threshold', '0.3', '--vad-model', self.vad_model])
        cmd.extend(['--output-file', basename, '--no-prints', '--print-progress', wav_path])
        subprocess.run(cmd)
        return f'{basename}.json'

    def translate_batch(self, entries: 'Mapping[int, SRTEntry]'):
        prompt = self.create_translation_prompt(entries)
        response = self.gemini_client.models.generate_content(
            model=self.gemini_model,
            contents=prompt,
        )
        translation_text = response.text

        # 解析翻译结果
        lines = translation_text.strip().split('\n')

        for line in lines:
            line = line.strip()
            if not line:
                continue

            # 匹配格式：[序号] 翻译文本
            match = re.match(r'\[(\d+)\]\s*(.+)', line)
            if match:
                index = int(match.group(1))
                translated_text = match.group(2).strip()
                entries[index].text = translated_text
                logging.info("[No.%d] - [%s --> %s] %s", index,
                             entries[index].start_time, entries[index].end_time, translated_text)

    def create_translation_prompt(self, entries: 'Mapping[int, SRTEntry]') -> str:
        entries_text = ""
        for entry in entries.values():
            entries_text += f"[{entry.index}] {entry.text}\n"

        prompt = f"""请将以下内容翻译成中文，请注意以下要求：

1. 保持原文的情感色彩和语调
2. 使用符合中文表达习惯的自然翻译
3. 保持角色对话的个性特点
4. 专有名词（人名、地名等）如果没有通用中文译名，可保持原文或音译
5. 保持字幕格式不要改变，字幕前面的序号使用中括号包裹

待翻译内容：
{entries_text}

请直接输出翻译结果："""

        return prompt

    def cleanup(self):
        if os.path.exists(self.base_path):
            shutil.rmtree(self.base_path)


class SRTEntry:
    """SRT item"""

    def __init__(self, index: int, start_time: str, end_time: str, text: str):
        self.index = index
        self.start_time = TimeCode(start_time)
        self.end_time = TimeCode(end_time)
        self.text = text.strip()

    def __str__(self):
        return f"{self.index}\n{str(self.start_time)} --> {str(self.end_time)}\n{self.text}\n\n"


class TimeCode(object):
    def __init__(self, data: Union[float, str]):
        if isinstance(data, float):
            self.code = self.seconds_to_code(data)
        elif isinstance(data, str) and seconds_pattern.match(data):
            self.code = data
        elif isinstance(data, str) and seconds_with_milliseconds_pattern.match(data):
            self.code = f'{data},000'
        else:
            raise TypeError("seconds must be a string or a float")

    def __str__(self):
        return self.code

    def without_millis(self):
        prefix, _ = self.code.split(",")
        return prefix

    @property
    def seconds(self) -> float:
        h, m, rest = self.code.split(":")
        if "," in rest:
            s, ms = rest.split(",")
        else:
            s = rest
            ms = 0
        return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000

    @staticmethod
    def seconds_to_code(seconds: float) -> str:
        hours = int(seconds) // 3600
        minutes = (int(seconds) % 3600) // 60
        secs = int(seconds) % 60
        millis = round((seconds - int(seconds)) * 1000)
        return f"{hours:02}:{minutes:02}:{secs:02},{millis:03}"

    def is_zero(self) -> bool:
        return self.code == '00:00:00,000'

    def add(self, code: 'TimeCode') -> 'TimeCode':
        seconds = self.seconds + code.seconds
        return TimeCode(seconds)


def valid_file(s: str) -> str:
    if not os.path.isfile(s):
        raise argparse.ArgumentTypeError(f"invalid file input")
    return s


def main():
    parser = argparse.ArgumentParser(description='Generate srt file from video by Whisper.cpp')
    parser.add_argument('input_file', type=valid_file, help='input filename')
    parser.add_argument('-wm', '--model', required=True, type=valid_file, help='Whisper.cpp model file path')
    parser.add_argument('-vm', '--vad-model', type=valid_file,
                        help='Whisper.cpp vad model file path, ignore vad if not provided')
    parser.add_argument('-gm', '--gemini-model', type=str, default=default_gemini_model,
                        help='use which gemini model to translate transcription')
    parser.add_argument('-gk', '--gemini-key', type=str, help='gemini key, no translation will be done if not set')
    parser.add_argument('-l', '--language', default='auto', help='language, default is "auto"')
    parser.add_argument('-c', '--cut-times', nargs='*', help='time to split the video, example: -c 10:00:00 50:00:00')
    parser.add_argument('-o', '--output', help='output filename (default [original].srt)')
    args = parser.parse_args()

    if not args.cut_times:
        cut_times = []
    else:
        cut_times = [TimeCode(ct) for ct in args.cut_times]

    output = args.output
    if not output:
        output = os.path.splitext(args.input_file)[0] + '.srt'

    handler = VideoHandler(whisper_model=args.model, gemini_model=args.gemini_model, gemini_api_key=args.gemini_key,
                           vad_model=args.vad_model, language=args.language, cut_times=cut_times)
    handler.run(args.input_file, output)


if __name__ == '__main__':
    main()
