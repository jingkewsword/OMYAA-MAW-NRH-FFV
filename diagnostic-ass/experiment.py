import hashlib, importlib.util, json, re, subprocess
from decimal import Decimal
from pathlib import Path
from PIL import Image, ImageChops

root = Path(__file__).resolve().parent
out = root / 'output'
out.mkdir(exist_ok=True)
spec = importlib.util.spec_from_file_location('oracle', root.parent / 'tests/helpers/ass-stacking-pixel-oracle.py')
o = importlib.util.module_from_spec(spec)
spec.loader.exec_module(o)

def digest(data): return hashlib.sha256(data).hexdigest()
def compare(a, b):
    diff = ImageChops.difference(a, b)
    return {'hash_a': digest(a.tobytes()), 'hash_b': digest(b.tobytes()),
            'bbox': diff.getbbox(), 'changed_pixels': sum(any(p) for p in diff.getdata()),
            'max_delta': max(max(p) for p in diff.getdata())}
def render(name, text, time, w=1280, h=720):
    path = out / (name + '.ass')
    path.write_text(text, encoding='utf-8')
    return o.render(path, out / (name + '.png'), w, h, time)

def quantize(text, quantum):
    def f(m):
        vals = [round(float(x)/quantum)*quantum for x in m[1].split(',')]
        return r'\pos(' + ','.join(format(x, '.10g') for x in vals) + ')'
    return re.sub(r'\\pos\(([^)]*)\)', f, text)

def exact_translate(source, padding):
    translated = o.translate_ass(source, padding)
    positions = iter(re.findall(r'\\pos\(([^)]*)\)', source))
    def replace(match):
        values = next(positions).split(',')
        return r'\pos(' + ','.join(str(Decimal(v) + padding) for v in values) + ')'
    return re.sub(r'\\pos\(([^)]*)\)', replace, translated)

scaled = (root / 'scaled.ass').read_text(encoding='utf-8')
report = {'input_sha256': {p.name: digest(p.read_bytes()) for p in [root/'scaled.ass', root/'grouped.ass', root/'standalone.ass', root/'original-native.png', root/'original-guard.png']}, 'cases': {}}
report['environment'] = {'ffmpeg': subprocess.check_output(['ffmpeg','-version'], text=True).splitlines()[0], 'font': subprocess.check_output(['fc-match','Arial'], text=True).strip(), 'libass': subprocess.check_output(['dpkg-query','-W','libass9'], text=True).strip()}
original = Image.open(root/'original-native.png').convert('RGB')
originalguard = Image.open(root/'original-guard.png').convert('RGB').crop((256,256,1536,976))
report['cases']['original_artifacts'] = compare(original, originalguard)
for name, source in [('fractional', scaled), ('integer', quantize(scaled, 1)), ('binary_1_64', quantize(scaled, 1/64))]:
    native, fonts = render(name, source, 1000)
    repeat, _ = render(name+'-repeat', source, 1000)
    report['cases'][name] = {'repeat': compare(native, repeat), 'font': fonts}
    for padding in (128, 256, 512):
        guard, gfonts = render(f'{name}-guard-{padding}', o.translate_ass(source, padding), 1000, 1280+2*padding, 720+2*padding)
        report['cases'][name][f'guard_{padding}'] = compare(native, guard.crop((padding,padding,1280+padding,720+padding)))
        report['cases'][name][f'guard_{padding}']['font'] = gfonts
    if name == 'fractional': report['cases'][name]['vs_original_native'] = compare(native, original)
    exact, _ = render(name+'-guard-256-exact', exact_translate(source, 256), 1000, 1792, 1232)
    report['cases'][name]['guard_256_exact'] = compare(native, exact.crop((256,256,1536,976)))

group = (root/'grouped.ass').read_text(encoding='utf-8')
stand = (root/'standalone.ass').read_text(encoding='utf-8')
# Retain only the active main event; compare its shifted clock to the original
# event at exactly the same explicit alignment and position.
group_lines = group.splitlines()
active = next(l for l in group_lines if l.startswith('Dialogue: 0,0:00:00.50,0:00:01.50,'))
group_single = '\n'.join(l for l in group_lines if not l.startswith('Dialogue:')) + '\n' + active + '\n'
stand_same = stand.replace('{\\fade', '{\\an8\\q2\\pos(640,171)\\fs64\\fsp0\\bord0\\shad0}{\\fade')
restart = group_single.replace('\\fade(255,0,255,-500,500,1000,1500)', '\\fade(255,0,255,0,1000,1500,2000)').replace('\\t(-500,500,2,\\fs120)', '\\t(0,1000,2,\\fs120)')
for time in (750, 1000, 1250):
    a, fonts = render(f'clock-group-{time}', group_single, time)
    b, _ = render(f'clock-same-{time}', stand_same, time)
    c, _ = render(f'clock-restart-{time}', restart, time)
    report['cases'][f'clock_{time}'] = {'group_vs_same': compare(a,b), 'group_vs_restart': compare(a,c), 'font': fonts}
(out/'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
print(json.dumps(report, indent=2))

# A binary-exact 2x scale retains the right-edge clipping case without
# requiring fractional viewport translation to be raster-invariant.
candidate = (root / 'scaled-exact-factor.ass').read_text(encoding='utf-8')
base, _ = render('candidate-2x-native', candidate, 1000)
report['cases']['candidate_2x'] = {}
for padding in (128, 256, 512):
    guard, _ = render(f'candidate-2x-guard-{padding}', o.translate_ass(candidate,padding),1000,1280+2*padding,720+2*padding)
    report['cases']['candidate_2x'][f'guard_{padding}'] = compare(base,guard.crop((padding,padding,1280+padding,720+padding)))
clip = re.sub(r'\\pos\(([^,]+),([^)]*)\)', lambda m: r'\pos('+str(Decimal(m[1])+80)+','+m[2]+')', candidate)
clip_path=out/'candidate-2x-clipped.ass'
clip_path.write_text(clip,encoding='utf-8')
report['cases']['candidate_2x_clip_negative'] = o.inspect(clip_path,1000,out/'candidate-2x-clipped',padding=256)
for time in (750,1750):
    actual=(root/f'candidate-clock-grouped-{time}.ass').read_text(encoding='utf-8')
    control=(root/f'candidate-clock-standalone-{time}.ass').read_text(encoding='utf-8')
    restarted=(root/f'candidate-clock-restarted-{time}.ass').read_text(encoding='utf-8')
    a,_=render(f'fixture-clock-grouped-{time}',actual,time)
    b,_=render(f'fixture-clock-control-{time}',control,time)
    c,_=render(f'fixture-clock-restarted-{time}',restarted,time)
    report['cases'][f'fixture_clock_{time}']={'same':compare(a,b),'restart':compare(a,c)}
(out/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')