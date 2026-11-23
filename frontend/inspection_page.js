import { api, h } from '/base.js'
import { banner, bind, options, signal } from '/ice_tools.js'

const zones = {nw:'北西',nc:'北中',ne:'北东',sw:'南西',sc:'南中',se:'南东'}
const state = {draft:'测量中',cleared:'已放行',repair:'需修整'}
function surfaceGrid(row) {
  return `<dl class="surface-grid">${Object.entries(zones).map(([code,label])=>{
    const actual = row.zones[code]
    const bad = actual && (actual.thickness < 18 || actual.thickness > 33 || actual.groove > 2)
    return `<div class="${bad?'damaged-location':''}"><dt>${label}</dt><dd>${actual?`${actual.thickness} mm 厚 · 槽 ${actual.groove} mm`:'待测'}</dd></div>`
  }).join('')}</dl>`
}
export async function inspection(root,user) {
  const [rows,rinks] = await Promise.all([api('/api/surveys'),api('/api/rinks')])
  const repairs = rows.filter(r=>r.status==='repair')
  root.innerHTML = `<article class="ice-board">${banner('冰面实况 · 六区','冰厚沟槽巡检','各区厚度 18–33 mm，沟槽 ≤2 mm，全场厚差 ≤5 mm。修整后另开复检。')}
    <div class="survey-layout"><section>${rows.map(row=>`<section class="survey-sheet"><h2>${h(row.ticket)} · ${h(row.rink_name)} · ${h(state[row.status])}</h2>
      <p>${h(row.inspected_on)}${row.retest_of?` · 复检 #${row.retest_of}`:''}${row.thickness_range!=null?` · 厚差 ${row.thickness_range} mm`:''}</p>
      ${surfaceGrid(row)}
      ${row.status==='draft'&&user.role==='operator'?`<form data-zone="${row.id}" class="ice-form"><label>区位${options('zone',Object.keys(zones),k=>k,k=>zones[k])}</label>
      <div class="pair"><label>厚度 mm<input name="thickness_mm" type="number" step=".1" min="1" required></label><label>沟槽 mm<input name="groove_mm" type="number" step=".1" min="0" required></label></div>
      <button>记录测点</button>${signal}</form>`:''}
      ${row.status==='draft'&&user.role==='reviewer'?`<form data-sign="${row.id}"><button>签署巡检结论</button>${signal}</form>`:''}</section>`).join('')||'<p>还没有巡检。先建立冰面巡检单。</p>'}</section>
      <aside class="ice-panel"><h2>建立巡检单</h2>${user.role==='operator'?`<form id="new-survey" class="ice-form">
      <label>单号<input name="ticket" placeholder="ICE-1124" required></label><label>冰面${options('rink_code',rinks,r=>r.code,r=>r.name)}</label>
      <label>巡检日期<input name="inspected_on" type="date" required></label>
      <label>承接修整<select name="retest_of"><option value="">首检</option>${repairs.map(r=>`<option value="${r.id}">${h(r.ticket)} · ${h(r.rink_name)}</option>`).join('')}</select></label>
      <button>开检</button>${signal}</form>`:'<p>录入员实测，复核员签结论。</p>'}</aside></div></article>`
  const update=()=>inspection(root,user)
  bind(root,'#new-survey',async body=>{await api('/api/surveys','POST',{...body,retest_of:Number(body.retest_of)||null});await update()})
  bind(root,'[data-zone]',async (body,d)=>{await api(`/api/surveys/${d.zone}/zones`,'PUT',body);await update()})
  bind(root,'[data-sign]',async (_,d)=>{await api(`/api/surveys/${d.sign}/sign`,'POST');await update()})
}
