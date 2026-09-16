from __future__ import annotations

from datetime import datetime
from pathlib import Path
import re
import shutil

TARGET = Path(r"E:\Real-time-situation-map\yuqing-v1\03_live_system\web\index.html")

NEW_BLOCK = r'''    const CORE_MINORITY_LANGS=["维吾尔语","藏语","蒙古语","壮语"];
    const MINORITY_LANG_PRIORITY=["维吾尔语","藏语","蒙古语","壮语","哈萨克语","彝语","朝鲜语"];
    function canonicalLanguageName(name){
      const s=String(name||"").trim();
      if(/维吾尔|维语|维文/i.test(s))return "维吾尔语";
      if(/藏语|藏文/i.test(s))return "藏语";
      if(/蒙古语|蒙古文|蒙语|蒙文/i.test(s))return "蒙古语";
      if(/壮语|壮文/i.test(s))return "壮语";
      if(/哈萨克/i.test(s))return "哈萨克语";
      if(/彝语|彝文/i.test(s))return "彝语";
      if(/朝鲜语|朝鲜文|韩语|韩文/i.test(s))return "朝鲜语";
      return s;
    }
    function isMinorityLanguageName(name){
      const s=canonicalLanguageName(name);
      if(!s)return false;
      if(/汉语|中文|普通话|英语|英文|English|未知|待核实|阿拉伯字母语言|拉丁字母待核实/i.test(s))return false;
      return MINORITY_LANG_PRIORITY.includes(s);
    }
    function languageRows(){
      const source=(D.languagePlatform||D.langSpotlight||[]);
      const by=new Map();
      source.forEach(x=>{
        const name=canonicalLanguageName(x.name||x.lang||"");
        if(!isMinorityLanguageName(name))return;
        const old=by.get(name)||{name,value:0,record:""};
        old.value+=Number(x.value||x.count||0);
        if(!old.record&&x.record)old.record=x.record;
        by.set(name,old);
      });
      CORE_MINORITY_LANGS.forEach(name=>{
        if(!by.has(name))by.set(name,{name,value:0,record:""});
      });
      return [...by.values()].sort((a,b)=>{
        const ai=MINORITY_LANG_PRIORITY.indexOf(a.name),bi=MINORITY_LANG_PRIORITY.indexOf(b.name);
        const ap=ai<0?999:ai,bp=bi<0?999:bi;
        return ap-bp||Number(b.value||0)-Number(a.value||0);
      });
    }'''


def main():
    if not TARGET.exists():
        raise SystemExit(f"Target not found: {TARGET}")

    text = TARGET.read_text(encoding="utf-8")
    if "CORE_MINORITY_LANGS" in text and "MINORITY_LANG_PRIORITY" in text:
        print("Suqi minority-language panel patch already appears to be installed.")
        return

    pattern = re.compile(
        r"    function isMinorityLanguageName\(name\)\{.*?\n    \}\n"
        r"    function languageRows\(\)\{.*?\n    \}",
        re.S,
    )
    match = pattern.search(text)
    if not match:
        raise SystemExit("Could not locate languageRows()/isMinorityLanguageName() block; no changes made.")

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = TARGET.with_name(TARGET.name + f".bak_minority_lang_{stamp}")
    shutil.copy2(TARGET, backup)

    patched = pattern.sub(NEW_BLOCK, text, count=1)
    TARGET.write_text(patched, encoding="utf-8")

    print("Suqi minority-language panel patch installed successfully.")
    print(f"Backup: {backup}")
    print(f"Target: {TARGET}")
    print("The panel will prioritize 维吾尔语 / 藏语 / 蒙古语 / 壮语 and exclude 汉语/英语 from the minority-language cards.")
    print("Restart server.py (or hard-refresh the browser) after applying the patch.")


if __name__ == "__main__":
    main()
