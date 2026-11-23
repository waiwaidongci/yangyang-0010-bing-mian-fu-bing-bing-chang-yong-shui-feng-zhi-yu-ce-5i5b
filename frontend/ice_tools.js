import { h } from '/base.js'

export const signal = '<output aria-live="polite"></output>'
export const options = (name,values,value,label) => `<select name="${h(name)}" required>${values.map(row=>`<option value="${h(value(row))}">${h(label(row))}</option>`).join('')}</select>`
export const banner = (tag,title,details) => `<header class="ice-heading"><p>${h(tag)}</p><h1>${h(title)}</h1><p>${h(details)}</p></header>`
export function bind(root, selector, action) {
  root.querySelectorAll(selector).forEach(form => {
    form.onsubmit = async event => {
      event.preventDefault()
      const button = form.querySelector('button'), status = form.querySelector('output')
      status.textContent = '提交中…'
      button.disabled = true
      try { await action(Object.fromEntries(new FormData(form)),form.dataset) }
      catch (error) { status.className='error-text';status.textContent=error.message }
      finally { button.disabled=false }
    }
  })
}
