"""Small local parameter check. Fixed test text; no meeting/user content."""
import base64
import json
import os
import re
import sys
import time
import urllib.request
from pathlib import Path

root = Path(__file__).resolve().parents[1]
os.chdir(root)
sys.path.insert(0, str(root))
from backend.text_segments import split_text
import numpy as np
import soundfile as sf
from supertonic import TTS

folder = root / ".run" / "vietnamese-tts-check"
text = json.loads((folder / "samples.json").read_text(encoding="utf-8"))["long"]
model = TTS(model_dir=root / ".model-cache" / "supertonic3", auto_download=False, intra_op_num_threads=4)
report = []
for voice in ("M1", "F1"):
    for limit, steps, speed in ((450,5,1.12), (300,5,1.12), (450,8,1.12)):
        np.random.seed(42)
        started = time.perf_counter()
        parts = []
        chunks = split_text(text, limit)
        for index, part in enumerate(chunks):
            if index:
                parts.append(np.zeros(round(model.sample_rate*.12), dtype=np.float32))
            wav, _ = model.synthesize(part, voice_style=model.get_voice_style(voice), lang="vi",total_steps=steps,speed=speed,silence_duration=.12,verbose=False)
            parts.append(wav.reshape(-1))
        audio = np.concatenate(parts)
        generation = time.perf_counter()-started
        filename = f"{voice}-limit{limit}-steps{steps}-speed{speed}.wav"
        sf.write(folder/filename,audio,model.sample_rate,subtype="PCM_16")
        pcm = np.clip(np.interp(np.linspace(0,len(audio)-1,round(len(audio)*16000/model.sample_rate)),np.arange(len(audio)),audio)*32767,-32768,32767).astype('<i2')
        request = urllib.request.Request('http://127.0.0.1:8765/dictate',data=json.dumps({'pcm16_base64':base64.b64encode(pcm.tobytes()).decode(),'sample_rate':16000,'source_language':'vi','target_language':'vi','translate':False,'mode':'fast'}).encode(),headers={'Content-Type':'application/json'})
        with urllib.request.urlopen(request,timeout=120) as response:
            transcript=json.load(response)['transcript']
        expected = re.findall(r'\w+',text.casefold())
        actual = re.findall(r'\w+',transcript.casefold())
        previous = list(range(len(actual)+1))
        for index,word in enumerate(expected,1):
            current=[index]
            for second,other in enumerate(actual,1):
                current.append(min(current[-1]+1,previous[second]+1,previous[second-1]+(word!=other)))
            previous=current
        item={'voice':voice,'limit':limit,'steps':steps,'speed':speed,'generation_seconds':round(generation,3),'audio_seconds':round(len(audio)/model.sample_rate,3),'word_error_rate':round(previous[-1]/len(expected),3),'file':filename,'transcript':transcript}
        report.append(item)
        print(json.dumps({key:value for key,value in item.items() if key!='transcript'}),flush=True)
(folder/'tuning.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
