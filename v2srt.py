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
import openai
from typing import Union, Mapping
from itertools import batched

logging.basicConfig(stream=sys.stdout, level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
seconds_pattern = re.compile(r'\d{2}:\d{2}:\d{2},\d{3}')
seconds_with_milliseconds_pattern = re.compile(r'\d{2}:\d{2}:\d{2}')


class VideoHandler(object):
    def __init__(self, whisper_model: str, openai_model: str , openai_api_key: str, language: str, url: str):
        self.whisper_model = whisper_model
        self.openai_model = openai_model
        self.language = language
        self.base_path = tempfile.mkdtemp(prefix='v2srt')
        self.translate_threshold = 50
        if openai_api_key:
            self.openai_client = openai.OpenAI(api_key=openai_api_key, base_url=url)
        else:
            self.openai_client = None
        atexit.register(self.cleanup)
        logging.info("base working directory: %s", self.base_path)

    def run(self, video_path: str, output: str):
        wav_path = self.video_to_wav(video_path)
        logging.info("wav file path: %s", wav_path)
        with open(output+'.srt', 'w', encoding='utf-8') as fout:
            transcription_path = self.generate_transcription(wav_path)
            logging.info("transcription file path: %s", transcription_path)
            with open(transcription_path, 'rb') as fin:
                data = json.load(fin)
            
            base = 1
            for batch in batched(data['segments'], self.translate_threshold):
                logging.info("start to translate from No.%d to No.%d", base, base+len(batch)-1)
                entries = {base+i: SRTEntry(index=base+i, start_time=segment['start'],
                                end_time=segment['end'], text=segment["text"]) for i, segment in enumerate(batch)}
                base += len(batch)
                if self.openai_client:
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

    def generate_transcription(self, wav_path: str) -> str:
        basename, _ = os.path.splitext(wav_path)
        cmd = ["whisper", "--language", self.language, "--model", self.whisper_model, '--output_dir', self.base_path, wav_path]
        subprocess.run(cmd, stdout=subprocess.DEVNULL)
        return f'{basename}.json'

    def translate_batch(self, entries: 'Mapping[int, SRTEntry]'):
        logging.info("Start translating...")
        prompt = self.create_translation_prompt(entries)
        response = self.openai_client.chat.completions.create(
            model=self.openai_model,
            messages=[
                {"role": "system", "content": "You are a translator for video subtitles."},
                {"role": "user", "content": prompt}
            ]
        )
        translation_text = response.choices[0].message.content

        lines = translation_text.strip().split('\n')

        for line in lines:
            line = line.strip()
            if not line:
                continue

            match = re.match(r'\[(\d+)\]\s*(.+)', line)
            if match:
                index = int(match.group(1))
                translated_text = match.group(2).strip()
                original_text = entries[index].text
                entries[index].text = f"{original_text}\n{translated_text}"

        logging.info("Translation completed.")

    def create_translation_prompt(self, entries: 'Mapping[int, SRTEntry]') -> str:
        entries_text = ""
        for entry in entries.values():
            entries_text += f"[{entry.index}] {entry.text}\n"

        prompt = f"""下面是一段视频中的部分字幕，请将它们翻译成中文，请注意以下要求：

1. 保持原文的情感色彩和语调
2. 使用符合中文表达习惯的自然翻译
3. 保持角色对话的个性特点
4. 专有名词（人名、地名等）如果没有通用中文译名，可保持原文或音译
5. 保持内容格式不要改变，字幕前面的序号使用中括号包裹

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
    parser = argparse.ArgumentParser(description='Generate srt file from video by Whisper')
    parser.add_argument('input_file', type=valid_file, help='input filename')
    parser.add_argument('-wm', '--model', default='turbo', type=str, help='Whisper model name, default is "turbo"')
    parser.add_argument('-om', '--openai-model', type=str, default="google/gemini-2.5-flash",
                        help='use which deepseek model to translate transcription')
    parser.add_argument('-ok', '--openai-key', type=str, help='openai key, no translation will be done if not set')
    parser.add_argument('-l', '--language', default='en', help='language, default is "en"')
    parser.add_argument('-o', '--output', help='output filename (default [original].srt)')
    parser.add_argument('-url', '--url', type=str, default="https://openrouter.ai/api/v1",
                        help='the base url for openai compatible api, default is "https://openrouter.ai/api/v1"')
    args = parser.parse_args()


    output = args.output
    if not output:
        output = os.path.splitext(args.input_file)[0]

    handler = VideoHandler(whisper_model=args.model, openai_model=args.openai_model, openai_api_key=args.openai_key,
                           language=args.language, url=args.url)
    handler.run(args.input_file, output)


if __name__ == '__main__':
    main()
