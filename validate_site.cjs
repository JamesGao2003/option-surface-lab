const fs=require('fs'),vm=require('vm');
const root=__dirname+'/';
const data=JSON.parse(fs.readFileSync(root+'data_snapshot.json'));
const reference=JSON.parse(fs.readFileSync(root+'metric_reference.json'));
const elements={};const charts={};
function element(id){return elements[id]||(elements[id]={textContent:'',value:id==='side'?'Call':'',checked:true,hidden:false,addEventListener(){}})}
element('dataset').textContent=JSON.stringify(data);
const context={document:{getElementById:element},Plotly:{react:(id,traces,layout)=>{charts[id]={traces,layout};}},navigator:{},console};
vm.createContext(context);vm.runInContext(fs.readFileSync(root+'app.js','utf8'),context);
let checked=0;
for(const r of reference){
 const got=vm.runInContext(`stats('${r.date}','${r.side}')`,context);
 for(const [key,actual] of Object.entries({denominator:got.eligible.length,mid_only:got.midOnly,percent:got.percent,paired:got.pairs.length,median:got.median})){
 if(actual===null?r[key]!==null:Math.abs(actual-r[key])>1e-10)throw Error(JSON.stringify({key,actual,expected:r}));
 }
 element('date').value=r.date;element('side').value=r.side;vm.runInContext('render()',context);
 for(const t of charts.cloud.traces){if(t.x.length!==t.y.length||t.x.length!==t.z.length)throw Error('Unequal coordinates');if(t.z.some(v=>v===null||!Number.isFinite(v)||v<0))throw Error('Invalid price');if(t.x.some(v=>v<0))throw Error('Expired contract in cloud');}
 checked++;
}
element('date').value=data.default_date;element('side').value='Call';element('mid').checked=false;element('trade').checked=false;vm.runInContext('render()',context);
if(element('empty').hidden)throw Error('No empty state when both fields hidden');
if(charts.cloud.traces.some(t=>t.visible))throw Error('Toggle broken');
const html=fs.readFileSync(root+'index.html','utf8');
if(html.includes('__DATA__')||html.includes('/*__APP__*/')||html.includes('/*__PLOTLY__*/'))throw Error('Unresolved placeholder');
if(/<script[^>]+src=/.test(html))throw Error('Remote script dependence');
for(const m of html.split('<script>')[0].matchAll(/href="([^"]+)"/g)){if(!fs.existsSync(root+m[1]))throw Error('Missing linked artifact: '+m[1]);}
console.log('PASS: '+checked+' date/type states; JS metrics agree with independent Python results; finite 3D coordinates; expiry checks; toggle and empty states; self-contained HTML; artifact links. Browser rendering has not been tested.');
console.log(reference.find(r=>r.date===data.default_date&&r.side==='Call'));
