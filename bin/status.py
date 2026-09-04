#!/usr/bin/env python3
import os, shutil
html = os.path.expanduser("~/jarvis-second-brain/viewer/index.html")
with open(html, encoding="utf-8") as f: s = f.read()
shutil.copy(html, html + ".bak-status")
pairs = [
 ("PENSANDO", "ΣΚΕΦΤΟΜΑΙ"),
 ("Pensando", "Σκέφτομαι"),
 ("pensando", "σκέφτομαι"),
 ("PROCESSANDO", "ΕΠΕΞΕΡΓΑΣΙΑ"),
 ("Processando", "Επεξεργασία"),
 ("OUVINDO", "ΑΚΟΥΩ"),
 ("Ouvindo", "Ακούω"),
 ("ouvindo", "ακούω"),
 ("ESCUTANDO", "ΑΚΟΥΩ"),
 ("Escutando", "Ακούω"),
 ("FALANDO", "ΜΙΛΑΩ"),
 ("Falando", "Μιλάω"),
 ("falando", "μιλάω"),
 ("CARREGANDO", "ΦΟΡΤΩΝΕΙ"),
 ("Carregando", "Φορτώνει"),
 ("AGUARDE", "ΠΕΡΙΜΕΝΕΤΕ"),
 ("Aguarde", "Περιμένετε"),
 ("GRAVANDO", "ΗΧΟΓΡΑΦΗΣΗ"),
 ("Gravando", "Ηχογράφηση"),
]
n = 0
for a, b in pairs:
    if a in s:
        c = s.count(a); s = s.replace(a, b); n += c
        print("replaced " + a + " -> " + b + " (" + str(c) + "x)")
with open(html, "w", encoding="utf-8") as f: f.write(s)
print("TOTAL " + str(n) + " replacements, backup -> index.html.bak-status")
