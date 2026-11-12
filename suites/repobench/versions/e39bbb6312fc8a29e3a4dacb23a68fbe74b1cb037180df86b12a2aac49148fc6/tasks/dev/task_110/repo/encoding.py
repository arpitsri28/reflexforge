import json
def encode(event):
    text=json.dumps(event,ensure_ascii=False,separators=(',',':'))
    body=text.encode('utf-8')
    return len(text).to_bytes(4,'big')+body
