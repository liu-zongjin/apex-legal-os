"""WebKit edit/save/reload check with anonymous calendar settings."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests.test_calendar_reminder_rules import CalendarReminderTests, ROOT
from playwright.sync_api import sync_playwright
fx=CalendarReminderTests(); fx.setUp()
source=(ROOT/'frontend/case-manager.js').read_text()
chunk=source[source.index('function renderCalendar()'):source.index('async function loadCalendar(')]
collect=source[source.index('function collectCalendarSettings()'):source.index('function setCalendarBusy(')]
with sync_playwright() as p:
    browser=p.webkit.launch()
    page=browser.new_page(viewport={'width':1440,'height':1100})
    page.set_content('<div id="content"></div>')
    page.add_style_tag(path=str(ROOT/'frontend/case-manager.css'))
    page.evaluate("window.$=id=>document.getElementById(id);window.esc=v=>String(v??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('\\\"','&quot;');window.state={calendarOptions:['匿名-iCloud'],calendarSettings:"+__import__('json').dumps(fx.scope['calendar_settings']())+"};")
    page.add_script_tag(content=chunk+collect+';renderCalendar();')
    assert page.locator('.calendar-rule-row').count()==4
    assert page.locator('#todoReminderDays').input_value()=='0'
    assert page.locator('#todoReminderTime').input_value()==''
    page.locator('#todoReminderDays').fill('7,3,0')
    page.locator('#todoReminderTime').fill('08:45')
    payload=page.evaluate('collectCalendarSettings()')
    result=fx.client.post('/api/case-manager/calendar/settings',json=payload)
    assert result.status_code==200,result.text
    page.evaluate('(s)=>{state.calendarSettings=s;renderCalendar();}',result.json()['settings'])
    assert page.locator('#todoReminderDays').input_value()=='7,3,0'
    assert page.locator('#todoReminderTime').input_value()=='08:45'
    page.screenshot(path='/tmp/stella-calendar-rules.png',full_page=True)
    browser.close()
fx.doCleanups()
print('WebKit: four reminder rules, edit/save/reload verified against isolated API')
