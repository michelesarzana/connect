import json, os
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
d = json.load(open(os.path.join(ROOT, 'docs', 'data', 'metrics.json'), encoding='utf-8'))
t = open(os.path.join(ROOT, 'scripts', 'template.html'), encoding='utf-8').read()
js = json.dumps(d, ensure_ascii=False).replace('</', '<\\/')
assert '/*DATA*/null' in t
os.makedirs(os.path.join(ROOT, 'docs'), exist_ok=True)
open(os.path.join(ROOT, 'docs', 'index.html'), 'w', encoding='utf-8').write(t.replace('/*DATA*/null', js))
print('ok docs/index.html')
