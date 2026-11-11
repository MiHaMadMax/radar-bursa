// node render.js <width> <height>  -> renders every *.html in cwd to .png
const {chromium}=require('playwright');const fs=require('fs');
const W=+process.argv[2]||1080,H=+process.argv[3]||1350;
(async()=>{const b=await chromium.launch();const p=await b.newPage({viewport:{width:W,height:H}});
for(const f of fs.readdirSync('.').filter(f=>f.endsWith('.html')).sort()){await p.goto('file://'+process.cwd()+'/'+f);await p.waitForTimeout(150);await p.screenshot({path:f.replace('.html','.png')});}
await b.close();})();
