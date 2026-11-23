import { api, h, mount, waitJob } from '/base.js'
import { inspection } from '/inspection_page.js'
import { dispatch } from '/dispatch_page.js'
import { reconcile } from '/reconcile_page.js'

const pages = { schedule: '冰时安排', meter: '复冰计量', forecast: '预测回测', shifts: '班次签报', inspection: '冰面巡检', dispatch: '机组派车', reconcile: '表码对账' }
const states = { draft: '待计算', blocked: '超容量', ready: '待签审', stale: '待重算', suspended: '暂停执行', confirmed: '已签报' }
const models = { holt: 'Holt 趋势平滑', last: '前日值基线' }
let shiftId = null
let rinkCode = 'R-A'

const clock = value => String(value).slice(0, 5)
const liters = value => `${value} L`
const numeral = value => Number(value).toFixed(1)
const seal = state => `<span class="seal ${h(state)}">${h(states[state])}</span>`

function heading(kicker, title, description) {
  return `<header class="ice-heading"><p>${h(kicker)}</p><h1>${h(title)}</h1><p>${h(description)}</p></header>`
}

function shiftSelect(rows) {
  return `<label class="control">冰面 / 班次<select id="shift-select">${rows.map(row =>
    `<option value="${row.id}" ${row.id === shiftId ? 'selected' : ''}>${h(row.rink_name)} · ${h(row.operating_day)} · ${h(row.label)}</option>`).join('')}</select></label>`
}

function bindSelect(outlet, selector, change) {
  outlet.querySelector(selector)?.addEventListener('change', event => change(event.target.value))
}

async function chosenShift() {
  const shifts = await api('/api/shifts')
  const selected = shifts.find(s => s.id === shiftId) || shifts[0]
  shiftId = selected.id
  return { shifts, selected }
}

function bindShift(outlet, page, user) {
  bindSelect(outlet, '#shift-select', value => {
    shiftId = Number(value)
    page(outlet, user)
  })
}

function handle(form, callback) {
  if (!form) return
  form.addEventListener('submit', async event => {
    event.preventDefault()
    const button = form.querySelector('button')
    const output = form.querySelector('output')
    button.disabled = true
    output.textContent = '提交中…'
    try {
      await callback(Object.fromEntries(new FormData(form)))
    } catch (error) {
      output.textContent = error.message
      output.className = 'error-text'
    } finally {
      button.disabled = false
    }
  })
}

function minutes(value) {
  const [hour, minute] = String(value).split(':').map(Number)
  return 60 * hour + minute
}

function timetable(shift, rows) {
  const start = minutes(shift.start_time)
  const total = minutes(shift.end_time) - start
  const position = value => (minutes(value) - start) / total * 100
  return `<div class="graphic" aria-label="冰时相对班次时间线">
    <div class="time-axis"><span>${clock(shift.start_time)}</span><span>${clock(shift.end_time)}</span></div>
    <div class="ice-track">${rows.map(slot => {
      const left = position(slot.start_time)
      const width = position(slot.end_time) - left
      return `<span class="slot-bar ${slot.refill_reason ? 'refilled' : ''}" style="left:${left}%;width:${width}%" title="${h(slot.crew_label)}">${h(slot.booking_ref)}</span>`
    }).join('')}</div></div>`
}

function slotTable(rows) {
  if (!rows.length) return '<p class="empty-ice">当前班次暂无预约。请登记场次和预计复冰次数。</p>'
  return `<div class="sheet-scroll"><table><thead><tr><th>时段</th><th>冰时单</th><th>场次</th><th>复冰</th><th>开场前补水</th></tr></thead>
    <tbody>${rows.map(row => `<tr><td>${clock(row.start_time)}–${clock(row.end_time)}</td><td>${h(row.booking_ref)}</td>
      <td>${h(row.crew_label)}</td><td>${row.passes} 次</td><td>${h(row.refill_reason || '—')}</td></tr>`).join('')}</tbody></table></div>`
}

async function schedule(outlet, user) {
  const { shifts, selected } = await chosenShift()
  const rows = await api(`/api/shifts/${selected.id}/bookings`)
  outlet.innerHTML = `<article class="ice-board">${heading('北湾冰上中心 · 日程', '复冰预约', '按冰面和班次登记实际冰时，供备水预测统计复冰次数。')}
    <div class="shift-select">${shiftSelect(shifts)} ${seal(selected.validation_state)}</div>
    <div class="board-split">
      <section>${timetable(selected, rows)}${slotTable(rows)}</section>
      <aside class="ice-panel"><h2>登记冰时单</h2>
      ${user.role === 'operator' && selected.status !== 'confirmed' ? `<form class="ice-form" id="booking-form">
        <div class="pair"><label>冰时单号<input name="booking_ref" placeholder="SK-240" required></label>
        <label>复冰次数<input name="passes" type="number" value="1" min="1" max="4" required></label></div>
        <label>预约场次<input name="crew_label" placeholder="周末训练" minlength="2" required></label>
        <div class="pair"><label>开始<input name="start_time" type="time" required></label>
        <label>结束<input name="end_time" type="time" required></label></div><button>登记预约</button><output aria-live="polite"></output>
      </form>` : '<p>由录入员登记；签报后冰时会锁定。</p>'}</aside>
    </div></article>`
  bindShift(outlet, schedule, user)
  handle(outlet.querySelector('#booking-form'), async data => {
    await api(`/api/shifts/${selected.id}/bookings`, 'POST', { ...data, passes: Number(data.passes) })
    await schedule(outlet, user)
  })
}

async function meter(outlet, user) {
  const [rinks, rows] = await Promise.all([api('/api/rinks'), api(`/api/rinks/${rinkCode}/meter`)])
  const rink = rinks.find(item => item.code === rinkCode)
  outlet.innerHTML = `<article class="ice-board">${heading('设备室 · 水表账', '实测用水', '每块冰面分别登记水票和实际复冰次数。预测使用每次平均耗水量。')}
    <div class="meter-toolbar"><label class="control">冰面<select id="rink-select">${rinks.map(item =>
      `<option value="${h(item.code)}" ${item.code === rinkCode ? 'selected' : ''}>${h(item.name)}</option>`).join('')}</select></label>
      <span>${rink.surface_m2} 平方米 · 水箱 ${liters(rink.tank_liters)} · 备水余量 ${rink.buffer_percent}%</span></div>
    <div class="board-split">
      <section class="sheet-scroll"><table><thead><tr><th>计量日</th><th>水票</th><th>实际次数</th><th>总用水</th><th>每次均值</th></tr></thead>
        <tbody>${rows.map(row => `<tr><td>${h(row.metered_on)}</td><td>${h(row.source_ticket)}</td><td>${row.passes}</td>
        <td>${liters(row.volume_liters)}</td><td>${liters(numeral(row.liters_per_pass))}</td></tr>`).join('')}</tbody></table>
        ${rows.length ? '' : '<p class="empty-ice">暂无水票，请先录入最近计量日。</p>'}</section>
      <aside class="ice-panel"><h2>录入水票</h2>
      ${user.role === 'operator' ? `<form id="meter-form" class="ice-form">
        <label>计量日<input name="metered_on" type="date" required></label>
        <label>票号<input name="source_ticket" placeholder="WTR-1123" required></label>
        <div class="pair"><label>复冰次数<input name="passes" type="number" min="1" max="24" required></label>
        <label>总用水（L）<input name="volume_liters" type="number" min="20" required></label></div>
        <button>保存计量</button><output aria-live="polite"></output></form>` : '<p>由录入员上传水表记录。</p>'}
      <p>回测需要至少 12 天连续水票。</p></aside>
    </div></article>`
  bindSelect(outlet, '#rink-select', value => { rinkCode = value; meter(outlet, user) })
  handle(outlet.querySelector('#meter-form'), async data => {
    await api(`/api/rinks/${rinkCode}/meter`, 'POST', { ...data, passes: Number(data.passes), volume_liters: Number(data.volume_liters) })
    await meter(outlet, user)
  })
}

function segmentTable(report) {
  if (!report) return '<p class="empty-ice">暂无分段估算。先提交班次预测。</p>'
  return `<div class="sheet-scroll"><table><thead><tr><th>段首</th><th>包含冰时单</th><th>用水</th><th>容量线</th></tr></thead>
    <tbody>${report.segments.map(s => `<tr class="${s.liters > report.backtest.tank_liters ? 'over-limit' : ''}">
    <td>${h(s.start)}</td><td>${s.bookings.map(b => h(b.ref)).join('、')}</td><td>${liters(s.liters)}</td>
    <td>${liters(report.backtest.tank_liters)}</td></tr>`).join('')}</tbody></table></div>`
}

function evidenceSummary(label, forecast) {
  if (!forecast) return `<p>${h(label)}：尚无记录</p>`
  return `<p>${h(label)}：预测 #${forecast.id} · 峰值 ${liters(forecast.peak_segment_liters)} · 每次 ${liters(forecast.projected_liters_per_pass)}
    · ${forecast.within_capacity ? '容量内' : '<span class="error-text">超容量</span>'}</p>`
}

function executionList(rows) {
  if (!rows.length) return '<p class="empty-ice">没有可执行的冰时安排。</p>'
  return `<ul class="execution">${rows.map(row => `<li><strong>${clock(row.start_time)}–${clock(row.end_time)}</strong>
    ${h(row.booking_ref)} · ${h(row.crew_label)} · ${row.passes} 次复冰</li>`).join('')}</ul>`
}

function deskNote(suspension) {
  if (!suspension) return ''
  const returned = suspension.supplements.find(item => item.status === 'returned')
  if (!returned) return ''
  return `<p class="error-text">补单 #${h(returned.id)} 已被退回：${h(returned.returned_reason)}</p>`
}

function suspensionHistory(history) {
  if (!history.length) return ''
  return `<section class="suspension-history"><h2>停用与补单记录</h2>${history.map(item => `<article class="suspension-record">
    <p><strong>${item.released_at ? '已放行' : '暂停中'}</strong> · ${h(item.created_at)}</p>
    <p>${h(item.reason)}</p>
    <p>原签报峰值 ${liters(item.previous_peak)} · 更正重算峰值 ${liters(item.raised_peak)}</p>
    ${item.supplements.length ? `<p>补单：${item.supplements.map(s =>
      `#${s.id} ${h({prepared:'待签',signed:'已签',returned:'已退回'}[s.status])}${s.returned_reason ? `（${h(s.returned_reason)}）` : ''}`
    ).join('；')}</p>` : '<p>尚未登记补单。</p>'}
  </article>`).join('')}</section>`
}

async function shifts(outlet, user) {
  const { shifts: list, selected } = await chosenShift()
  const data = await api(`/api/shifts/${selected.id}/handover`)
  const shift = data.shift
  const suspended = shift.status === 'suspended'
  const signed = data.signed
  const candidate = suspended ? data.latest : null
  outlet.innerHTML = `<article class="ice-board">${heading('早班交接 · 放行', '备水班次签报', '每个满箱区段都须容纳预计用水。水票更正抬高已签峰值时暂停执行，复核补单后再放行。')}
    <div class="shift-select">${shiftSelect(list)} ${seal(shift.validation_state ?? shift.status)}</div>
    ${suspended ? `<section class="suspension-banner" role="alert"><h2>班次已暂停执行</h2>
      <p>${h(shift.suspended_reason)}</p>
      <p>暂停时间 ${h(shift.suspended_at)}</p></section>` : ''}
    <div class="handover-layout">
      <section>
        <h2>原签报</h2>
        ${signed ? `<p>签审 ${h(signed.by)} · ${h(signed.at)}</p>${evidenceSummary('原签报证据', signed.forecast)}
          ${!signed.evidence_current ? '<p class="error-text">水票已有更正，原签报引用更正前的旧水票。重算峰值未抬高，原签报继续有效。</p>' : ''}
          ${segmentTable(signed.forecast)}` : '<p class="empty-ice">该班次尚未签报。</p>'}
        <h2>当前可执行的安排</h2>
        ${suspended
          ? `<p class="error-text">暂停执行，补单签署前不得开工，没有可执行的备水安排。${candidate ? `候选重算峰值 ${liters(candidate.peak_segment_liters)}。` : ''}</p>
             <h3>暂存的冰时</h3>${executionList(data.scheduling)}`
          : shift.status === 'confirmed'
            ? `<p>执行签报预测 #${h(data.executable?.id)}，当前水箱容量 ${liters(shift.tank_liters)}。</p>${segmentTable(data.executable)}`
            : `<p>当前状态 ${h(states[shift.validation_state] ?? shift.status)}，尚未放行。</p>${executionList(data.scheduling)}`}
        ${suspensionHistory(data.history)}
      </section>
      <aside class="ice-panel"><h2>${suspended ? '补单复核' : '签报与调整'}</h2>
        ${suspended ? `
          ${evidenceSummary('候选重算', candidate)}
          ${candidate ? segmentTable(candidate) : '<p>请先重算候选峰值：在预测回测页提交重算。</p>'}
          ${deskNote(data.suspension)}
          ${data.pending_supplement ? `<p>补单 #${h(data.pending_supplement.id)} 待复核签署：${h(data.pending_supplement.note)}</p>`
            : (user.role === 'operator' && candidate ? `<form id="supplement-form" class="ice-form">
              <label>补单说明<input name="note" placeholder="已在 08:10 补满水箱" minlength="2" required></label>
              <button>提交补单</button><output aria-live="polite"></output></form>`
              : '<p>由录入员登记补单，复核员签署后放行。</p>')}
          ${data.pending_supplement && user.role === 'reviewer' ? `<form id="sign-supplement"><button>签署补单放行</button><output aria-live="polite"></output></form>` : ''}
          <p>补单峰值超过水箱 ${liters(shift.tank_liters)} 时会被退回。</p>`
          : `${signed ? `<p>签审 ${h(signed.by)} · 预测 #${signed.forecast?.id}</p>` : ''}
          ${user.role === 'reviewer' && data.latest && shift.status !== 'confirmed' ? '<form id="confirm-form"><button>确认备水班次</button><output aria-live="polite"></output></form>' : ''}
          <p><a href="#forecast">转到预测回测 →</a></p>`}
        ${user.role === 'operator' && shift.status !== 'confirmed' && data.scheduling.length ? `<h2>调整冰时与补水</h2>
        <form id="refill-form" class="ice-form"><label>场次<select name="booking_id">
        ${data.scheduling.map((r, index) => `<option value="${r.booking_id}" ${index === data.scheduling.length - 1 ? 'selected' : ''}>${h(r.booking_ref)} · ${h(r.crew_label)}</option>`).join('')}
        </select></label>
        <div class="pair"><label>调整后开始<input type="time" name="start_time" required></label>
        <label>调整后结束<input type="time" name="end_time" required></label></div>
        <label>补水记录<input name="refill_reason" placeholder="留空为不补水"></label>
        <button>更新排程</button><output aria-live="polite"></output></form>` : ''}
      </aside>
    </div>
  </article>`
  bindShift(outlet, shifts, user)
  handle(outlet.querySelector('#confirm-form'), async () => {
    await api(`/api/shifts/${shift.id}/confirm`, 'POST', { forecast_id: data.latest.id })
    await shifts(outlet, user)
  })
  handle(outlet.querySelector('#supplement-form'), async ({ note }) => {
    await api(`/api/shifts/${shift.id}/supplements`, 'POST', { forecast_id: candidate.id, note })
    await shifts(outlet, user)
  })
  handle(outlet.querySelector('#sign-supplement'), async () => {
    const outcome = await api(`/api/shifts/${shift.id}/supplements/${data.pending_supplement.id}/sign`, 'POST')
    await shifts(outlet, user)
    return outcome
  })
  const form = outlet.querySelector('#refill-form')
  if (form) {
    const populate = () => {
      const row = data.scheduling.find(r => r.booking_id === Number(form.elements.booking_id.value))
      form.elements.start_time.value = clock(row.start_time)
      form.elements.end_time.value = clock(row.end_time)
      form.elements.refill_reason.value = row.refill_reason ?? ''
    }
    form.elements.booking_id.onchange = populate
    populate()
    handle(form, async ({ booking_id, refill_reason, ...times }) => {
      await api(`/api/shifts/${shift.id}/bookings/${booking_id}`, 'PUT', { ...times, refill_reason: refill_reason.trim() || null })
      await shifts(outlet, user)
    })
  }
}

async function forecast(outlet, user) {
  const { shifts, selected } = await chosenShift()
  const [report] = await api(`/api/shifts/${selected.id}/forecasts`)
  outlet.innerHTML = `<article class="ice-board">
    ${heading('水量模型 · 验证', '预测与滚动回测', '用最近连续计量日训练，留末四天逐日检验，按平均绝对误差择优。')}
    <div class="shift-select">${shiftSelect(shifts)} ${seal(selected.validation_state)}
    ${user.role !== 'viewer' && selected.status !== 'confirmed' ? '<form id="forecast-form"><button>重算班次预测</button><output aria-live="polite"></output></form>' : ''}</div>
    ${report ? `<div class="forecast-layout">
    <section class="forecast-summary"><h2>${h(models[report.model])}</h2><strong>${liters(report.projected_liters_per_pass)}</strong>
      <p>每次备水，含 ${report.backtest.buffer_percent}% 余量</p>
      <p>${report.backtest.observations} 个计量日 · 预测距离最后计量 ${report.backtest.horizon} 天</p>
      <div class="error-bench"><span>Holt MAE ${liters(numeral(report.backtest.errors.holt))}</span><span>前日值 MAE ${liters(numeral(report.backtest.errors.last))}</span></div></section>
    <section><h2>最近四个留末日（L/次）</h2><div class="sheet-scroll"><table><thead><tr><th>计量日</th><th>实测</th><th>Holt</th><th>前日值</th></tr></thead>
      <tbody>${report.backtest.holdout.map(day => `<tr><td>${h(day.date)}</td><td>${numeral(day.actual)}</td><td>${numeral(day.holt)}</td><td>${numeral(day.last)}</td></tr>`).join('')}</tbody></table></div></section>
    </div><h2>水箱分段估算</h2>${segmentTable(report)}` : '<p class="empty-ice">此班次尚未计算。核对复冰预约和计量历史后提交。</p>'}
    </article>`
  bindShift(outlet, forecast, user)
  handle(outlet.querySelector('#forecast-form'), async () => {
    const result = await api(`/api/shifts/${selected.id}/forecasts`, 'POST')
    await waitJob(result.job_id)
    if (outlet.isConnected && shiftId === selected.id) await forecast(outlet, user)
  })
}

const renderers = { schedule, meter, forecast, shifts, inspection, dispatch, reconcile }
mount({ title: '冰面复冰', kicker: '北湾冰上中心', pages, render: (page, outlet, user) => renderers[page](outlet, user) })
