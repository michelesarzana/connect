import json, os
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS = os.path.join(ROOT, 'docs')
d = json.load(open(os.path.join(DOCS, 'data', 'metrics.json'), encoding='utf-8'))
try:
    att = json.load(open(os.path.join(DOCS, 'data', 'attivita.json'), encoding='utf-8'))
except Exception:
    att = {'campi': [], 'righe': []}
t = open(os.path.join(ROOT, 'scripts', 'template.html'), encoding='utf-8').read()
enc = lambda x: json.dumps(x, ensure_ascii=False, separators=(',', ':')).replace('</', '<\\/')
assert '/*DATA*/null' in t and '/*ATT*/null' in t
t = t.replace('/*DATA*/null', enc(d)).replace('/*ATT*/null', enc(att['righe']))
open(os.path.join(DOCS, 'index.html'), 'w', encoding='utf-8').write(t)
print('ok docs/index.html', len(att['righe']), 'attivita')
