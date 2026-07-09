(function(){
  'use strict';
  const SETTINGS_KEY = 'tds.browser.settings.v278';
  const PACK_BASE = '/static/i18n/';
  const DEFAULTS = { language: 'en', startupPage: 'overview', refreshMs: window.STAQTAPP_REFRESH_MS || 2000 };
  const FALLBACK_LANGUAGES = [
    {code:'en', nativeName:'English', englishName:'English'},
    {code:'es', nativeName:'Español', englishName:'Spanish'},
    {code:'pt', nativeName:'Português', englishName:'Portuguese'},
    {code:'ja', nativeName:'日本語', englishName:'Japanese'},
    {code:'de', nativeName:'Deutsch', englishName:'German'},
    {code:'fr', nativeName:'Français', englishName:'French'},
    {code:'it', nativeName:'Italiano', englishName:'Italian'}
  ];
  let manifest = { default: 'en', languages: FALLBACK_LANGUAGES };
  let packs = {};
  let packLoadErrors = [];
  const originalText = new WeakMap();
  const originalAttrs = new WeakMap();

  function languageChoices(){
    const source = Array.isArray(manifest.languages) && manifest.languages.length ? manifest.languages : FALLBACK_LANGUAGES;
    const choices = source.filter((lang) => lang && lang.code);
    return choices.length ? choices : FALLBACK_LANGUAGES;
  }
  function defaultLanguageCode(){
    const choices = languageChoices();
    const preferred = manifest.default || DEFAULTS.language;
    return choices.some((lang) => lang.code === preferred) ? preferred : (choices[0] && choices[0].code) || DEFAULTS.language;
  }
  function sanitizeSettings(settings){
    const clean = Object.assign({}, DEFAULTS, settings || {});
    const allowedRefresh = new Set([0,250,500,1000,2000,5000]);
    clean.refreshMs = Number(clean.refreshMs);
    if (!allowedRefresh.has(clean.refreshMs)) clean.refreshMs = DEFAULTS.refreshMs;
    const codes = new Set(languageChoices().map((lang) => lang.code));
    if (!codes.has(clean.language)) clean.language = defaultLanguageCode();
    return clean;
  }
  function loadSettings(){
    try { return sanitizeSettings(JSON.parse(localStorage.getItem(SETTINGS_KEY) || '{}')); }
    catch (_) { return Object.assign({}, DEFAULTS); }
  }
  function saveSettings(settings){ localStorage.setItem(SETTINGS_KEY, JSON.stringify(sanitizeSettings(settings))); }
  function currentLanguage(){ return loadSettings().language || defaultLanguageCode(); }
  function packFor(code){ return packs[code] || packs[defaultLanguageCode()] || packs.en || {}; }
  function translate(value, code){
    if (value === undefined || value === null) return value;
    const key = String(value).trim();
    if (!key) return value;
    const selected = packFor(code || currentLanguage());
    const fallback = packFor('en');
    return selected[key] || fallback[key] || value;
  }
  function translatePattern(value, code){
    const text = translate(value, code);
    const settings = loadSettings();
    return String(text).replaceAll('{refresh}', Math.round((Number(settings.refreshMs) || 0) / 1000));
  }

  async function fetchJson(url){
    const response = await fetch(url, { cache: 'no-store' });
    if (!response.ok) throw new Error(`${url} ${response.status}`);
    return response.json();
  }
  async function loadPacks(){
    packLoadErrors = [];
    try { manifest = await fetchJson(PACK_BASE + 'manifest.json'); }
    catch (err) { manifest = { default: 'en', languages: FALLBACK_LANGUAGES }; packLoadErrors.push('manifest'); }
    await Promise.all((manifest.languages || FALLBACK_LANGUAGES).map(async (lang) => {
      try { packs[lang.code] = await fetchJson(`${PACK_BASE}${lang.code}.json`); }
      catch (err) { packs[lang.code] = packs[lang.code] || {}; packLoadErrors.push(lang.code); }
    }));
    document.documentElement.dataset.i18nStatus = packLoadErrors.length ? 'fallback' : 'ready';
  }

  function rememberTextNode(node){
    if (!originalText.has(node)) originalText.set(node, node.nodeValue);
    return originalText.get(node);
  }
  function rememberAttr(el, attr){
    let attrs = originalAttrs.get(el);
    if (!attrs) { attrs = {}; originalAttrs.set(el, attrs); }
    if (!(attr in attrs)) attrs[attr] = el.getAttribute(attr);
    return attrs[attr];
  }
  function translateNodeTree(root, code){
    const doc = root || document.body;
    const walker = document.createTreeWalker(doc, NodeFilter.SHOW_TEXT, {
      acceptNode(node){
        if (!node.nodeValue || !node.nodeValue.trim()) return NodeFilter.FILTER_REJECT;
        const parent = node.parentElement;
        if (!parent || ['SCRIPT','STYLE','NOSCRIPT'].includes(parent.tagName)) return NodeFilter.FILTER_REJECT;
        return NodeFilter.FILTER_ACCEPT;
      }
    });
    const nodes = [];
    while (walker.nextNode()) nodes.push(walker.currentNode);
    nodes.forEach((node) => {
      const original = rememberTextNode(node);
      const leading = original.match(/^\s*/)[0];
      const trailing = original.match(/\s*$/)[0];
      const core = original.trim();
      if (core) node.nodeValue = leading + translatePattern(core, code) + trailing;
    });
    doc.querySelectorAll('[title], [aria-label], [data-i18n-title]').forEach((el) => {
      ['title','aria-label'].forEach((attr) => {
        if (el.hasAttribute(attr)) el.setAttribute(attr, translatePattern(rememberAttr(el, attr), code));
      });
      const titleKey = el.getAttribute('data-i18n-title');
      if (titleKey) el.setAttribute('title', translatePattern(titleKey, code));
    });
  }

  function populateLanguageSelect(){
    const select = document.getElementById('tds-language-select');
    if (!select) return;
    const settings = loadSettings();
    select.innerHTML = '';
    languageChoices().forEach((lang) => {
      const option = document.createElement('option');
      const nativeName = lang.nativeName || lang.englishName || String(lang.code).toUpperCase();
      const englishName = lang.englishName || nativeName;
      option.value = lang.code;
      option.textContent = nativeName === englishName ? nativeName : `${nativeName} (${englishName})`;
      select.appendChild(option);
    });
    select.value = settings.language;
    if (select.value !== settings.language) select.value = defaultLanguageCode();
    if (!select.value && select.options.length) select.selectedIndex = 0;
    select.dataset.currentLanguage = select.value || defaultLanguageCode();
    select.onchange = () => {
      const next = loadSettings();
      next.language = select.value;
      saveSettings(next);
      applyTranslations();
    };
  }
  function initSettingsControls(){
    const settings = loadSettings();
    const startup = document.getElementById('tds-startup-select');
    const refresh = document.getElementById('tds-refresh-select');
    if (startup) {
      startup.value = settings.startupPage;
      startup.onchange = () => { const next = loadSettings(); next.startupPage = startup.value; saveSettings(next); };
    }
    if (refresh) {
      refresh.value = settings.refreshMs > 0 ? String(settings.refreshMs) : 'manual';
      refresh.onchange = () => {
        const next = loadSettings();
        next.refreshMs = refresh.value === 'manual' ? 0 : Number(refresh.value);
        saveSettings(next);
        applyTranslations();
        if (window.TDSDashboardRefresh) window.TDSDashboardRefresh.restart();
      };
    }
    const about = document.getElementById('tds-about-button');
    const dialog = document.getElementById('tds-about-dialog');
    const close = document.getElementById('tds-about-close');
    if (about && dialog) about.onclick = () => { dialog.setAttribute('aria-hidden','false'); };
    if (close && dialog) close.onclick = () => { dialog.setAttribute('aria-hidden','true'); };
    if (dialog) dialog.addEventListener('click', (ev) => { if (ev.target === dialog) dialog.setAttribute('aria-hidden','true'); });
  }
  function applyTranslations(root){
    const code = currentLanguage();
    document.documentElement.lang = code;
    translateNodeTree(root || document.body, code);
    populateLanguageSelect();
  }
  function getRefreshMS(){ const ms = Number(loadSettings().refreshMs); return ms > 0 ? ms : 0; }
  function goToStartupPage(){
    const startup = loadSettings().startupPage;
    if (startup && startup !== 'overview') {
      setTimeout(() => { const el = document.getElementById(startup); if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' }); }, 120);
    }
  }

  window.TDSI18N = { t: translatePattern, applyTranslations, loadPacks, packLoadErrors: () => packLoadErrors.slice() };
  window.TDSBrowserSettings = { load: loadSettings, save: saveSettings, getRefreshMS };

  document.addEventListener('DOMContentLoaded', async () => {
    await loadPacks();
    populateLanguageSelect();
    initSettingsControls();
    applyTranslations();
    goToStartupPage();
  });
})();
