import time
import random
import threading
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

bot_status = {
    "running": False,
    "logs": [],
    "completed": 0,
    "total": 0,
    "error": None,
    "paused": False,
    "pending_inputs": [],
    "answers": None,
}

_resume_event = threading.Event()
_resume_event.set()


def log(msg):
    bot_status["logs"].append(msg)
    if len(bot_status["logs"]) > 500:
        bot_status["logs"] = bot_status["logs"][-300:]


def setup_driver(headless=True):
    opts = Options()
    if headless:
        opts.add_argument("--headless=new")
    opts.add_argument("--start-maximized")
    opts.add_argument("--disable-notifications")
    opts.add_argument("--log-level=3")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_argument("--disable-extensions")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_experimental_option('excludeSwitches', ['enable-logging', 'enable-automation'])
    opts.add_experimental_option('useAutomationExtension', False)
    opts.page_load_strategy = 'eager'
    svc = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=svc, options=opts)
    driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    return driver


def scroll_to(driver, el):
    try:
        driver.execute_script("arguments[0].scrollIntoView({block:'center',behavior:'instant'});", el)
        time.sleep(0.1)
        return True
    except:
        return False


def quick_type(el, text):
    try:
        el.clear()
        el.send_keys(str(text))
        return True
    except:
        return False


def safe_click(driver, el):
    for _ in range(3):
        try:
            el.click()
            return True
        except:
            try:
                driver.execute_script("arguments[0].click();", el)
                return True
            except:
                time.sleep(0.1)
    return False


class SmartRandomBot:
    def __init__(self, config):
        self.url = config.get("url", "")
        self.mode = config.get("mode", "random")
        self.speed_mode = config.get("speed_mode", "fast")
        self.rounds = int(config.get("rounds", 1))
        self.forbidden_words = config.get("forbidden_words", [])
        self.weight_map = {int(k): v for k, v in config.get("weight_map", {}).items()}
        self.dist_mode = int(config.get("dist_mode", 1))
        self.manual_pages = config.get("manual_pages", [])
        self.headless = config.get("headless", True)
        self.memory = []
        self.master_random_index = 0
        self.page_logic_buffer = {}

    def safe_click_dropdown(self, driver, el):
        try:
            scroll_to(driver, el)
            try:
                el.click()
            except:
                driver.execute_script("arguments[0].click();", el)
            WebDriverWait(driver, 3).until(
                EC.visibility_of_element_located((By.CSS_SELECTOR, 'div[role="option"]')))
            return True
        except:
            return False

    def smart_select(self, elements, is_matrix_row=False):
        if not elements:
            return None
        total = len(elements)
        valid_opts, valid_idx = [], []
        for i, el in enumerate(elements):
            try:
                dv = el.get_attribute("data-value")
                if dv == "__other_option__":
                    continue
                raw = el.get_attribute("aria-label") or el.text or dv or ""
                clean = "".join(raw.split())
                if "อื่นๆ" in clean or "other" in clean.lower():
                    continue
                forbidden = False
                for bad in self.forbidden_words:
                    if bad in clean or bad.lower() in clean.lower():
                        log(f"🚫 ข้าม: {raw.strip()}")
                        forbidden = True
                        break
                if not forbidden:
                    valid_opts.append(el)
                    valid_idx.append(i)
            except:
                continue
        if not valid_opts:
            return None
        if total in self.weight_map:
            ws = [self.weight_map[total][i] if i < len(self.weight_map[total]) else 0 for i in valid_idx]
            if sum(ws) > 0:
                return random.choices(valid_opts, weights=ws, k=1)[0]
        if self.dist_mode > 1 and not is_matrix_row:
            n = len(valid_opts)
            ws = [1/(i+1) for i in range(n)] if self.dist_mode == 2 else [1/((i+1)**2) for i in range(n)]
            return random.choices(valid_opts, weights=ws, k=1)[0]
        return random.choice(valid_opts)

    def scan_text_inputs_on_page(self, driver):
        found = []
        # has_any_global = มีข้อเขียนที่ตอบไปแล้วในหน้าก่อนหน้า
        has_any_global = len(self.page_logic_buffer) > 0
        try:
            questions = driver.find_elements(By.CSS_SELECTOR, 'div[role="listitem"]')
            for q_idx, q in enumerate(questions):
                inputs = q.find_elements(By.CSS_SELECTOR,
                    'input[type="text"]:not([type="hidden"]), textarea')
                for t_idx, t in enumerate(inputs):
                    lbl = t.get_attribute("aria-label") or ""
                    if "คำตอบอื่นๆ" in lbl or "Other" in lbl:
                        continue
                    if t.get_attribute("value"):
                        continue
                    title = f"คำถาม #{q_idx + 1}"
                    try:
                        h = q.find_element(By.CSS_SELECTOR, 'div[role="heading"]')
                        title = h.text.replace("\n", " ").strip()[:80]
                    except:
                        pass
                    # has_previous = มีข้อเขียนก่อนหน้าไม่ว่าจะหน้าไหน
                    has_previous = has_any_global or len(found) > 0
                    found.append({
                        "q_idx": q_idx,
                        "t_idx": t_idx,
                        "title": title,
                        "has_previous": has_previous,
                    })
        except:
            pass
        return found

    def pause_and_ask(self, pending_inputs):
        global _resume_event
        _resume_event.clear()
        bot_status["paused"] = True
        bot_status["pending_inputs"] = pending_inputs
        bot_status["answers"] = None
        log(f"⏸️ หยุดรอคำตอบข้อเขียน {len(pending_inputs)} ข้อ...")
        while not _resume_event.wait(timeout=1):
            if not bot_status["running"]:
                return

        bot_status["paused"] = False

    def auto_fill_current_page(self, driver, learn_mode=False, fixed_memory=None):
        time.sleep(0.5)
        # ไม่ reset page_logic_buffer ที่นี่ — ต้องจำ across pages
        # reset เฉพาะตอนเริ่ม learn round ใหม่ (ใน scan_and_learn)

        try:
            questions = driver.find_elements(By.CSS_SELECTOR, 'div[role="listitem"]')

            # PASS 1 (learn_mode): กรอก radio/checkbox ก่อน แล้วค่อย scan text inputs
            if learn_mode:
                for q_idx, q in enumerate(questions):
                    try:
                        rgs = q.find_elements(By.CSS_SELECTOR, 'div[role="radiogroup"]')
                        if rgs:
                            for rg in rgs:
                                opts = rg.find_elements(By.CSS_SELECTOR, 'div[role="radio"]')
                                if opts and not any(o.get_attribute("aria-checked") == "true" for o in opts):
                                    t = self.smart_select(opts, is_matrix_row=len(rgs) > 1)
                                    if t:
                                        scroll_to(driver, t)
                                        safe_click(driver, t)
                                        time.sleep(0.5 if self.speed_mode == "human" else 0.05)
                        else:
                            cbs = q.find_elements(By.CSS_SELECTOR, 'div[role="checkbox"]')
                            if cbs and len(cbs) > 1:
                                for cb in cbs:
                                    if cb.get_attribute("aria-checked") == "true":
                                        scroll_to(driver, cb)
                                        safe_click(driver, cb)
                                        time.sleep(0.3 if self.speed_mode == "human" else 0.05)
                                t = self.smart_select(cbs)
                                if t:
                                    scroll_to(driver, t)
                                    safe_click(driver, t)
                                    time.sleep(0.5 if self.speed_mode == "human" else 0.1)
                    except:
                        continue

                # หลัง fill radio/checkbox แล้ว scan text inputs ที่เหลือ
                pending = self.scan_text_inputs_on_page(driver)
                if pending:
                    self.pause_and_ask(pending)
                # PASS 1 เสร็จ — PASS 2 จะ fill text inputs ด้านล่าง

            for q_idx, q in enumerate(questions):
                try:
                    handled = False

                    radiogroups = q.find_elements(By.CSS_SELECTOR, 'div[role="radiogroup"]')
                    if radiogroups:
                        if not learn_mode:  # learn_mode กรอกไปแล้วใน PASS 1
                            for rg in radiogroups:
                                opts = rg.find_elements(By.CSS_SELECTOR, 'div[role="radio"]')
                                if not opts:
                                    continue
                                if not any(o.get_attribute("aria-checked") == "true" for o in opts):
                                    t = self.smart_select(opts, is_matrix_row=len(radiogroups) > 1)
                                    if t:
                                        scroll_to(driver, t)
                                        safe_click(driver, t)
                                        time.sleep(0.5 if self.speed_mode == "human" else 0.05)
                        handled = True

                    if not handled:
                        cbs = q.find_elements(By.CSS_SELECTOR, 'div[role="checkbox"]')
                        if cbs and len(cbs) > 1:
                            if not learn_mode:  # learn_mode กรอกไปแล้วใน PASS 1
                                for cb in cbs:
                                    if cb.get_attribute("aria-checked") == "true":
                                        scroll_to(driver, cb)
                                        safe_click(driver, cb)
                                        time.sleep(0.3 if self.speed_mode == "human" else 0.05)
                                t = self.smart_select(cbs)
                                if t:
                                    scroll_to(driver, t)
                                    safe_click(driver, t)
                                    time.sleep(0.5 if self.speed_mode == "human" else 0.1)
                            handled = True

                    text_inputs = q.find_elements(By.CSS_SELECTOR,
                        'input[type="text"]:not([type="hidden"]), textarea')
                    for t_idx, t_input in enumerate(text_inputs):
                        lbl = t_input.get_attribute("aria-label") or ""
                        if "คำตอบอื่นๆ" in lbl or "Other" in lbl:
                            continue
                        if t_input.get_attribute("value"):
                            continue
                        key = f"{q_idx}_{t_idx}"

                        if not learn_mode and fixed_memory is not None:
                            mem = next((x for x in fixed_memory
                                if x.get("type") == "text"
                                and x.get("q") == q_idx
                                and x.get("t") == t_idx), None)
                            if mem:
                                if "options_list" in mem:
                                    choices = mem["options_list"]
                                    if choices:
                                        if mem.get("is_linked", False):
                                            idx = self.master_random_index % len(choices)
                                        else:
                                            idx = random.randint(0, len(choices) - 1)
                                            self.master_random_index = idx
                                        scroll_to(driver, t_input)
                                        quick_type(t_input, choices[idx])
                                        log(f"✍️ [q{q_idx}] → {choices[idx]}")
                                elif mem.get("val"):
                                    scroll_to(driver, t_input)
                                    quick_type(t_input, mem["val"])
                            continue

                        if learn_mode:
                            answers = bot_status.get("answers") or {}
                            ans_data = answers.get(key)
                            if ans_data:
                                choices = ans_data.get("choices", [])
                                is_linked = ans_data.get("is_linked", False)
                                if choices:
                                    if is_linked:
                                        idx = self.master_random_index % len(choices)
                                    else:
                                        idx = random.randint(0, len(choices) - 1)
                                        self.master_random_index = idx
                                    selected = choices[idx]
                                    scroll_to(driver, t_input)
                                    quick_type(t_input, selected)
                                    log(f"✍️ [q{q_idx}] → {selected} (pos {idx+1}/{len(choices)})")
                                    self.page_logic_buffer[key] = {
                                        "options_list": choices,
                                        "is_linked": is_linked,
                                    }
                            else:
                                log(f"⚠️ ข้ามข้อเขียน [q{q_idx}]")
                            continue

                    listboxes = q.find_elements(By.CSS_SELECTOR, 'div[role="listbox"]')
                    for lb in listboxes:
                        if "เลือก" in (lb.text or ""):
                            scroll_to(driver, lb)
                            if self.safe_click_dropdown(driver, lb):
                                opts = driver.find_elements(By.CSS_SELECTOR, 'div[role="option"]')
                                t = self.smart_select(opts)
                                if t:
                                    safe_click(driver, t)
                                    time.sleep(0.5 if self.speed_mode == "human" else 0.15)
                                else:
                                    ActionChains(driver).send_keys(Keys.ESCAPE).perform()
                except:
                    continue
        except:
            pass

    def scrape_data(self, driver):
        data = []
        qs = driver.find_elements(By.CSS_SELECTOR, 'div[role="listitem"]')
        for qi, q in enumerate(qs):
            try:
                for ri, r in enumerate(q.find_elements(By.XPATH, './/div[@role="radio"]')):
                    if r.get_attribute("aria-checked") == "true":
                        data.append({"type":"radio","q":qi,"r":ri,"val":r.get_attribute("data-value")})
                saved = False
                for ci, c in enumerate(q.find_elements(By.XPATH, './/div[@role="checkbox"]')):
                    if c.get_attribute("aria-checked") == "true" and not saved:
                        data.append({"type":"checkbox","q":qi,"c":ci})
                        saved = True
                        break
                for ti, t in enumerate(q.find_elements(By.CSS_SELECTOR,
                        'input:not([type="hidden"]), textarea')):
                    val = t.get_attribute("value")
                    if val and t.get_attribute("role") not in ["radio","checkbox"]:
                        obj = {"type":"text","q":qi,"t":ti,"val":val}
                        k = f"{qi}_{ti}"
                        if k in self.page_logic_buffer:
                            obj["options_list"] = self.page_logic_buffer[k]["options_list"]
                            obj["is_linked"] = self.page_logic_buffer[k]["is_linked"]
                        data.append(obj)
                for li, lb in enumerate(q.find_elements(By.CSS_SELECTOR,'div[role="listbox"]')):
                    if "เลือก" not in lb.text:
                        data.append({"type":"dropdown","q":qi,"l":li,"val":lb.text.strip()})
            except:
                pass
        return data

    def scan_and_learn(self, driver):
        log("🎓 เริ่มต้นรอบเรียนรู้ (รอบที่ 1)...")
        self.memory = []
        self.page_logic_buffer = {}   # reset ครั้งเดียวตอนเริ่ม learn
        self.master_random_index = 0
        page_num = 1
        while True:
            log(f"📄 หน้าที่ {page_num}")
            self.auto_fill_current_page(driver, learn_mode=True)
            time.sleep(0.5)
            buttons = driver.find_elements(By.CSS_SELECTOR, 'div[role="button"]')
            target_btn, action_type = None, "unknown"
            for btn in buttons:
                t = btn.text.strip()
                if t in ["ถัดไป","Next","ต่อไป"]:
                    action_type = "next"; target_btn = btn; break
                if t in ["ส่ง","Submit","Send"]:
                    action_type = "submit"; target_btn = btn; break
            if not target_btn:
                break
            page_data = self.scrape_data(driver)
            self.memory.append({"page":page_num,"action":action_type,"inputs":page_data})
            scroll_to(driver, target_btn)
            safe_click(driver, target_btn)
            time.sleep(2)
            if action_type == "submit":
                log("✅ ส่งรอบที่ 1 เรียบร้อย")
                return
            page_num += 1

    def replay_sequence(self, driver):
        time.sleep(0.5)
        for step in self.memory:
            try:
                is_random = self.mode == "random" or (
                    self.mode == "mix" and step["page"] not in self.manual_pages)
                if is_random:
                    self.auto_fill_current_page(driver, learn_mode=False,
                                                fixed_memory=step["inputs"])
                else:
                    qs = driver.find_elements(By.CSS_SELECTOR, 'div[role="listitem"]')
                    for item in step["inputs"]:
                        try:
                            if item["q"] >= len(qs): continue
                            q = qs[item["q"]]
                            if item["type"] == "radio":
                                rs = q.find_elements(By.XPATH, './/div[@role="radio"]')
                                if len(rs) > item["r"]: safe_click(driver, rs[item["r"]])
                            elif item["type"] == "checkbox":
                                cs = q.find_elements(By.XPATH, './/div[@role="checkbox"]')
                                if len(cs) > item["c"]:
                                    if cs[item["c"]].get_attribute("aria-checked") != "true":
                                        safe_click(driver, cs[item["c"]])
                            elif item["type"] == "text":
                                ins = q.find_elements(By.CSS_SELECTOR,
                                    'input:not([type="hidden"]), textarea')
                                if len(ins) > item["t"]:
                                    if "options_list" in item:
                                        choices = item["options_list"]
                                        if choices:
                                            if item.get("is_linked", False):
                                                idx = self.master_random_index % len(choices)
                                            else:
                                                idx = random.randint(0, len(choices) - 1)
                                                self.master_random_index = idx
                                            quick_type(ins[item["t"]], choices[idx])
                                            log(f"✍️ [q{item['q']}] → {choices[idx]}")
                                    elif item.get("val"):
                                        quick_type(ins[item["t"]], item["val"])
                            elif item["type"] == "dropdown":
                                lbs = q.find_elements(By.CSS_SELECTOR, 'div[role="listbox"]')
                                if len(lbs) > item["l"]:
                                    scroll_to(driver, lbs[item["l"]])
                                    if self.safe_click_dropdown(driver, lbs[item["l"]]):
                                        tc = "".join(item["val"].split())
                                        for o in driver.find_elements(By.CSS_SELECTOR,
                                                'div[role="option"]'):
                                            if tc in "".join(o.text.split()):
                                                safe_click(driver, o); break
                                        else:
                                            ActionChains(driver).send_keys(Keys.ESCAPE).perform()
                        except: continue
                btns = driver.find_elements(By.CSS_SELECTOR, 'div[role="button"]')
                targets = (["ส่ง","Submit","Send"] if step["action"]=="submit"
                           else ["ถัดไป","Next","ต่อไป"])
                for btn in btns:
                    if btn.text.strip() in targets:
                        scroll_to(driver, btn)
                        safe_click(driver, btn)
                        time.sleep(1)
                        break
            except Exception as e:
                log(f"⚠️ Replay error: {e}")

    def run(self):
        global bot_status, _resume_event
        bot_status.update({
            "running": True, "logs": [], "completed": 0,
            "total": self.rounds, "error": None,
            "paused": False, "pending_inputs": [], "answers": None,
        })
        _resume_event.set()

        driver = None
        try:
            log("🚀 กำลังเปิดเบราว์เซอร์...")
            driver = setup_driver(self.headless)
            driver.get(self.url)
            time.sleep(1.5)
            log(f"🌐 เปิดฟอร์มสำเร็จ")
            log(f"⚙️ Mode: {self.mode} | Speed: {self.speed_mode} | Rounds: {self.rounds}")

            self.scan_and_learn(driver)
            completed = 1
            bot_status["completed"] = completed

            if self.speed_mode == "human" and self.rounds > 1:
                d = random.randint(10, 30)
                log(f"☕ พักเบรก {d} วินาที...")
                time.sleep(d)

            while completed < self.rounds:
                if not bot_status["running"]:
                    break
                log(f"\n>>> รอบที่ {completed + 1} / {self.rounds} <<<")
                driver.get(self.url)
                time.sleep(1.5)
                try:
                    self.replay_sequence(driver)
                    try:
                        WebDriverWait(driver, 5).until(EC.presence_of_element_located((By.XPATH,
                            "//*[contains(text(),'บันทึกคำตอบ') or "
                            "contains(text(),'response has been recorded') or "
                            "contains(text(),'ส่งคำตอบเพิ่ม')]")))
                        completed += 1
                        bot_status["completed"] = completed
                        log(f"✅ รอบที่ {completed} สำเร็จ!")
                        if self.speed_mode == "human" and completed < self.rounds:
                            d = random.randint(10, 30)
                            log(f"☕ พักเบรก {d} วินาที...")
                            time.sleep(d)
                    except:
                        log(f"❌ รอบที่ {completed + 1} ไม่สำเร็จ")
                except Exception as e:
                    log(f"⚠️ Error: {e}")

            log(f"\n🎉 เสร็จสิ้น {completed}/{self.rounds} รอบ")
        except Exception as e:
            bot_status["error"] = str(e)
            log(f"❌ Fatal: {e}")
        finally:
            if driver:
                try: driver.quit()
                except: pass
            bot_status["running"] = False
            bot_status["paused"] = False
            log("🔒 ปิดเบราว์เซอร์แล้ว")


_bot_thread = None

def start_bot(config):
    global _bot_thread, bot_status
    if bot_status.get("running"):
        return "บอทกำลังทำงานอยู่แล้ว"
    try:
        bot = SmartRandomBot(config)
        _bot_thread = threading.Thread(target=bot.run, daemon=True)
        _bot_thread.start()
        return None
    except Exception as e:
        return str(e)

def submit_text_answers(answers):
    global _resume_event
    bot_status["answers"] = answers
    bot_status["paused"] = False
    _resume_event.set()
    log("▶️ รับคำตอบแล้ว กำลังรันต่อ...")

def get_status():
    return dict(bot_status)

def stop_bot():
    global _resume_event
    bot_status["running"] = False
    _resume_event.set()
    bot_status["logs"].append("🛑 หยุดบอทโดยผู้ใช้")