import { api, h } from '/base.js'
import { banner, bind, options, signal } from '/ice_tools.js'

const nice = value => String(value).slice(0,5)
export async function dispatch(root,user) {
  const [{crews,allocations},shifts,surveys] = await Promise.all([api('/api/crew-board'),api('/api/shifts'),api('/api/surveys')])
  const grouped = await Promise.all(shifts.map(async shift => (await api(`/api/shifts/${shift.id}/bookings`)).map(row=>({...row,shift}))))
  const slots = grouped.flat().filter(row=>!allocations.some(a=>a.booking_id===row.id&&!a.revoked_at))
  const cleared = surveys.filter(row=>row.status==='cleared')
  root.innerHTML=`<article class="ice-board">${banner('复冰调度 · 机组占用','跨冰面班组派车','按每次 8 分钟和补水时长找连续空档，同时更新各机组的工作日占用。')}
    <div class="crew-layout"><section>${crews.map(crew=>`<section class="crew-strip"><h2>${h(crew.name)}</h2><p>覆盖 ${crew.max_surface_m2} m² · ${nice(crew.works_from)}–${nice(crew.works_until)}</p>
      ${allocations.filter(a=>a.crew_code===crew.code).map(a=>`<article class="${a.stale?'allocation-stale':''}"><strong>${nice(a.starts)}–${nice(a.ends)} · ${h(a.booking_ref)}</strong>
        <p>${h(a.service_day)} · ${h(a.rink_code)} · ${h(a.crew_label)}${a.revoked_at?' · 已撤回':a.stale?' · 冰时已变更，撤回后重派':''}</p>
        ${user.role==='operator'&&!a.revoked_at?`<form data-revoke="${a.id}"><button>撤回此派车</button>${signal}</form>`:''}</article>`).join('')||'<p>尚无派车。</p>'}</section>`).join('')}</section>
      <aside class="ice-panel"><h2>分配冰车</h2>${user.role==='operator'&&slots.length&&cleared.length?`<form id="assign" class="ice-form">
      <label>预约${options('booking_id',slots,r=>r.id,r=>`${r.shift.rink_name} · ${r.booking_ref} · ${nice(r.start_time)}`)}</label>
      <label>机组${options('crew_code',crews,r=>r.code,r=>r.name)}</label>
      <label>放行巡检${options('survey_id',cleared,r=>r.id,r=>`${r.rink_name} · ${r.ticket}`)}</label><button>寻找作业空档</button>${signal}</form>`:'<p>有已放行巡检的冰面才能安排机组。可从巡检页登记。</p>'}
      <a href="#inspection">查看冰面巡检 →</a></aside></div></article>`
  bind(root,'#assign',async body=>{await api('/api/crew-board/allocations','POST',{...body,booking_id:Number(body.booking_id),survey_id:Number(body.survey_id)});await dispatch(root,user)})
  bind(root,'[data-revoke]',async (_,d)=>{await api(`/api/crew-board/allocations/${d.revoke}/revoke`,'POST');await dispatch(root,user)})
}
