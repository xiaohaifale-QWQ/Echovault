"""测试各下载源是否可用"""
import urllib.request, ssl

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

urls = [
    ("hf-mirror", "https://hf-mirror.com/openai/whisper-tiny/resolve/main/pytorch_model.bin"),
    ("huggingface", "https://huggingface.co/openai/whisper-tiny/resolve/main/pytorch_model.bin"),
]

for name, url in urls:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Range": "bytes=0-1023"})
        resp = urllib.request.urlopen(req, context=ctx, timeout=15)
        cl = resp.headers.get("Content-Length", "?")
        print(f"[OK] {name}: HTTP {resp.status}, size={cl}")
    except Exception as e:
        print(f"[FAIL] {name}: {e}")
