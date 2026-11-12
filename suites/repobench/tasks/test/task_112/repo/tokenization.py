import re
def tokens(text): return set(re.findall(r'[^\W_]+',text.lower()))
def prepare(document):
    if not isinstance(document.key,str) or not document.key or not isinstance(document.title,str) or not document.title.strip() or not isinstance(document.body,str): raise ValueError('document')
    return tokens(document.title+' '+document.body)
