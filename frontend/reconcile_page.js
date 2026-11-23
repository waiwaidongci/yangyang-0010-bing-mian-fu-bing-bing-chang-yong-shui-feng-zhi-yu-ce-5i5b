import { api,h } from '/base.js'
import { banner,bind,options,signal } from '/ice_tools.js'

const state = {matched:'票表一致',pending:'差异待复核',retained:'保留原水票',corrected:'采用表码差'}
export async function reconcile(root,user) {
  const {registers,cases} = await api('/api/registers')
  root.innerHTML=`<article class="ice-board">${banner('机械刻度 · 对账','复冰水票校核','跨回零按表盘周期计算。偏差超过 5% 或至少 10 L 的容限进入复核。')}
    <div class="recon-layout"><section>${cases.map(row=>`<section class="meter-case ${h(row.state)}"><h2>${h(row.source_ticket)} · ${h(row.rink_name)} · ${h(state[row.state])}</h2>
      <dl><div><dt>原票</dt><dd>${row.ledger_liters} L</dd></div><div><dt>表码差</dt><dd>${row.measured_liters} L</dd></div>
      <div><dt>${row.rolled?'跨回零':'连续读数'}</dt><dd>${row.opening_mark} → ${row.closing_mark}</dd></div></dl>
      <p>${h(row.evidence)}${row.resolution?` · ${h(row.resolution)} · ${h(row.resolved_by)}`:''}</p>
      ${row.state==='pending'&&user.role==='reviewer'?`<form class="ice-form" data-rink="${h(row.rink_code)}" data-day="${h(row.metered_on)}">
      <label>决议<select name="use_measured"><option value="false">保留水票</option><option value="true">采用表码差，重算预测</option></select></label>
      <label>依据<input name="resolution" minlength="4" required></label><button>签署对账</button>${signal}</form>`:''}</section>`).join('')||'<p>尚未核对水票。先从对应机械表抄录首尾刻度。</p>'}</section>
      <aside class="ice-panel"><h2>录入机械表码</h2>${user.role==='operator'?`<form id="mark-form" class="ice-form">
      <label>水表${options('register_code',registers,r=>r.code,r=>r.description)}</label>
      <label>计量日<input name="metered_on" type="date" required></label>
      <div class="pair"><label>起码<input name="opening_mark" type="number" min="0" required></label><label>止码<input name="closing_mark" type="number" min="0" required></label></div>
      <label>来源及拍照编号<input name="evidence" minlength="4" required></label><button>计算票表差</button>${signal}</form>`:'<p>录入员提交表码，复核员确认差异。</p>'}</aside></div></article>`
  bind(root,'#mark-form',async body=>{await api('/api/registers/checks','POST',{...body,opening_mark:Number(body.opening_mark),closing_mark:Number(body.closing_mark)});await reconcile(root,user)})
  bind(root,'[data-rink]',async (body,d)=>{await api(`/api/registers/checks/${d.rink}/${d.day}/resolve`,'POST',{...body,use_measured:body.use_measured==='true'});await reconcile(root,user)})
}
