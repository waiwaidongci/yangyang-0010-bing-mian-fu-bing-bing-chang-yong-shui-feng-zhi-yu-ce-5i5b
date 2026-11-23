import { api, h, mount, waitJob } from '/base.js'
import { inspection } from '/inspection_page.js'
import { dispatch } from '/dispatch_page.js'
import { reconcile } from '/reconcile_page.js'

const pages = { schedule: '冰时安排', meter: '复冰计量', forecast: '预测回测', shifts: '班次签报', inspection: '冰面巡检', dispatch: '机组派车', reconcile: '表码对账' }
const states = { draft: '待计算', blocked: '超容量', ready: '待签审', stale: '待重算', confirmed: '已签报' }
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

async function shifts(outlet, user) {
  const { shifts: list, selected } = await chosenShift()
  const [reports, rows] = await Promise.all([
    api(`/api/shifts/${selected.id}/forecasts`), api(`/api/shifts/${selected.id}/bookings`)
  ])
  const latest = reports[0]
  outlet.innerHTML = `<article class="ice-board">${heading('早班交接 · 放行', '备水班次签报', '每个满箱区段都须容纳预计用水。调整冰时或补水后，重算再签报。')}
    <div class="shift-select">${shiftSelect(list)} ${seal(selected.validation_state)}</div>
    <div class="handover-layout">
      <section><h2>预计分段峰值 ${selected.peak_segment_liters != null ? liters(selected.peak_segment_liters) : '待计算'}</h2>
      ${segmentTable(latest)}
      <p>当前水箱容量 ${liters(selected.tank_liters)}。每次补水需为前场结束后预留至少 15 分钟。</p>
      ${selected.validation_state === 'stale' ? '<p class="error-text">冰时或计量版本已变化，请到预测回测重算。</p>' : ''}
      <p><a href="#forecast">转到预测回测 →</a></p>
      ${selected.confirmed_by ? `<p>签审 ${h(selected.confirmed_by)} · 预测 #${selected.confirmed_forecast}</p>` : ''}
      ${user.role === 'reviewer' && latest && selected.status !== 'confirmed' ? '<form id="confirm-form"><button>确认备水班次</button><output aria-live="polite"></output></form>' : ''}
      </section>
      ${user.role === 'operator' && selected.status !== 'confirmed' && rows.length ? `<aside class="ice-panel"><h2>调整冰时与补水</h2>
        <form id="refill-form" class="ice-form"><label>场次<select name="booking_id">
        ${rows.map((r, index) => `<option value="${r.id}" ${index === rows.length - 1 ? 'selected' : ''}>${h(r.booking_ref)} · ${h(r.crew_label)}</option>`).join('')}
        </select></label>
        <div class="pair"><label>调整后开始<input type="time" name="start_time" required></label>
        <label>调整后结束<input type="time" name="end_time" required></label></div>
        <label>补水记录<input name="refill_reason" placeholder="留空为不补水"></label>
        <button>更新排程</button><output aria-live="polite"></output></form>
       </aside>` : ''}
    </div>
  </article>`
  bindShift(outlet, shifts, user)
  handle(outlet.querySelector('#confirm-form'), async () => {
    await api(`/api/shifts/${selected.id}/confirm`, 'POST', { forecast_id: latest.id })
    await shifts(outlet, user)
  })
  const form = outlet.querySelector('#refill-form')
  if (form) {
    const populate = () => {
      const row = rows.find(r => r.id === Number(form.elements.booking_id.value))
      form.elements.start_time.value = clock(row.start_time)
      form.elements.end_time.value = clock(row.end_time)
      form.elements.refill_reason.value = row.refill_reason ?? ''
    }
    form.elements.booking_id.onchange = populate
    populate()
    handle(form, async ({ booking_id, refill_reason, ...times }) => {
      await api(`/api/shifts/${selected.id}/bookings/${booking_id}`, 'PUT', { ...times, refill_reason: refill_reason.trim() || null })
      await shifts(outlet, user)
    })
  }
}

const renderers = { schedule, meter, forecast, shifts, inspection, dispatch, reconcile }
mount({ title: '冰面复冰', kicker: '北湾冰上中心', pages, render: (page, outlet, user) => renderers[page](outlet, user) })
