from pathlib import Path
import re,base64
root=Path(__file__).parent;dist=root/'dist';html=(dist/'index.html').read_text();css=next((dist/'assets').glob('*.css')).read_text()
def embed(m):
 url=m.group(1).strip('"\'');f=dist/'assets'/url.split('?')[0].split('/')[-1]
 return 'url(data:font/woff2;base64,'+base64.b64encode(f.read_bytes()).decode()+')' if f.suffix=='.woff2' and f.exists() else m.group(0)
css=re.sub(r'url\(([^)]+)\)',embed,css)
js=next((dist/'assets').glob('*.js')).read_text().replace('</script','<\\/script')
html=re.sub(r'<script[^>]+src="[^"]+"[^>]*></script>',lambda m:'<script type="module">'+js+'</script>',html)
html=re.sub(r'<link[^>]+rel="stylesheet"[^>]*>',lambda m:'<style>'+css+'</style>',html)
(root/'communication-preview.html').write_text(html);(dist/'communication-preview.html').write_text(html)
