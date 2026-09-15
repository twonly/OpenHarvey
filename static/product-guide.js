import {labels as liveLabels} from './i18n.js';
import {t as tr} from './i18n.js';
import {accountLanguage} from './language-ui.js';
// Authenticated readers use their account locale on this standalone page too.
void fetch('/api/me',{credentials:'same-origin'}).then(async response=>{if(response.ok)await accountLanguage(await response.json());}).catch(()=>{});
// Explanatory examples only: no model calls or persisted configuration.
const scenarios = liveLabels({
  strict: ['示例结论 · 命中', '90 日超过 60 日基线', 'Agent 应指出付款期限偏离公司基线，引用原文并提出调整建议。实际分析还需要检查起算条件、例外和其他条款的影响。'],
  relaxed: ['示例结论 · 该期限未超基线', '90 日符合这一项期限要求', '在示例假设下，这一期限本身未偏离 90 日基线。它不等于整份合同无风险，Agent 仍需检查起算条件、其他判定要点和其余启用风险项。'],
  disabled: ['示例范围 · 不要求逐项覆盖', '该项退出完整审查的必查清单', 'Agent 不再被要求为这一停用项生成逐项审查记录。合同中的 90 日约定仍然存在，Agent 在其他分析中也可能讨论它；停用不代表风险消失。'],
});
const buttons = [...document.querySelectorAll('[data-scenario]')];
for (const button of buttons) {
  button.addEventListener('click', () => {
    const values = scenarios[button.dataset.scenario];
    for (const item of buttons) item.setAttribute('aria-pressed', String(item === button));
    ['example-label', 'example-title', 'example-description'].forEach((id, index) => {
      document.getElementById(id).textContent = values[index];
    });
  });
}
document.addEventListener('ui-language-changed',()=>document.querySelector('[data-scenario][aria-pressed="true"]')?.click());
const links = [...document.querySelectorAll('.guide-nav a')];
const sections = links.map(link => document.querySelector(link.hash));
let pending = false;
function updateSection() {
  pending = false;
  let current = sections[0];
  for (const section of sections) if (section.getBoundingClientRect().top <= 150) current = section;
  for (const link of links) {
    if (link.hash === '#' + current.id) link.setAttribute('aria-current', 'location');
    else link.removeAttribute('aria-current');
  }
}
window.addEventListener('scroll', () => {
  if (!pending) { pending = true; requestAnimationFrame(updateSection); }
}, { passive: true });
window.addEventListener('resize', updateSection);
updateSection();
