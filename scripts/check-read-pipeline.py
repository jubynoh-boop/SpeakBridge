"""Running-engine smoke tests with fixed, non-private text fixtures."""
import base64
import io
import json
import time
import urllib.request
from pathlib import Path
import numpy as np
import soundfile as sf

root=Path(__file__).resolve().parents[1]
folder=root/'.run'/'read-pipeline-check'
folder.mkdir(parents=True,exist_ok=True)
def post(path,payload):
    started=time.perf_counter()
    request=urllib.request.Request('http://127.0.0.1:8765'+path,data=json.dumps(payload).encode(),headers={'Content-Type':'application/json'})
    with urllib.request.urlopen(request,timeout=120) as response:
        result=json.load(response)
    return result, round(time.perf_counter()-started,3)

source=("Invoice 101 must be paid on Friday. The amount is 2500 USD and the payment method is bank transfer. "
        "Invoice 102 must be paid on Monday. The amount is 3700 USD and the customer wants a written confirmation. "
        "Invoice 103 must be paid on Tuesday. The amount is 4800 USD and the order must keep its original product name. "
        "Do not leave out the final instruction: contact customer support before changing the delivery date.")
report=[]
result,elapsed=post('/text/read',{'text':source,'source_language':'en','target_language':'vi','read_mode':'translation','voices':{'vi':'M1'}})
audio_bytes=base64.b64decode(result.pop('audio_base64'))
audio,rate=sf.read(io.BytesIO(audio_bytes),dtype='float32')
if not len(audio) or not np.isfinite(audio).all() or np.sqrt(np.mean(audio**2))<.0001:
    raise RuntimeError('Silent/invalid Vietnamese audio')
for number in ('101','102','103','2500','3700','4800'):
    if number not in result['text'].replace(',','').replace('.',''):
        raise RuntimeError('Translation lost a fixture number: '+number)
if result['spoken_language']!='vi' or result['voice']!='M1':
    raise RuntimeError('Reader did not honor selected target voice')
(folder/'translated-vietnamese.wav').write_bytes(audio_bytes)
report.append({'test':'long_translation_read','elapsed_seconds':elapsed,**result})
print(json.dumps({'test':'long_translation_read','elapsed_seconds':elapsed,'source_chars':len(source),'spoken_chars':len(result['text']),'timing':result['timing']},ensure_ascii=True),flush=True)
result,elapsed=post('/text/read',{'text':'Read this original English sentence without translating it.','source_language':'en','target_language':'vi','read_mode':'source','voices':{'en':'af_heart'}})
result.pop('audio_base64')
if result['spoken_language']!='en' or result['voice']!='af_heart' or result['timing']['translation_seconds']!=0:
    raise RuntimeError('Original read mode unexpectedly translated text')
report.append({'test':'original_read','elapsed_seconds':elapsed,**result})
print('Original read mode honors English / Heart; no translation.',flush=True)
with urllib.request.urlopen('http://127.0.0.1:8765/tts/voices') as response:
    catalog=json.load(response)['languages']
for language,voices in catalog.items():
    for voice in voices:
        if not voice['installed']:
            raise RuntimeError('Missing voice: '+voice['id'])
        result,elapsed=post('/tts/test',{'language':language,'voice':voice['id']})
        waveform,rate=sf.read(io.BytesIO(base64.b64decode(result['audio_base64'])),dtype='float32')
        if not len(waveform) or not np.isfinite(waveform).all() or np.sqrt(np.mean(waveform**2))<.0001:
            raise RuntimeError('Silent/invalid voice: '+voice['id'])
        item={'test':'voice','language':language,'voice':voice['id'],'elapsed_seconds':elapsed,'audio_seconds':round(len(waveform)/rate,3)}
        report.append(item)
        print(json.dumps(item),flush=True)
(folder/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
