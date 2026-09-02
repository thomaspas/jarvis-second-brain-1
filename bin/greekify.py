#!/usr/bin/env python3
import re, os, shutil

root = os.path.expanduser("~/jarvis-second-brain")
server = os.path.join(root, "server.py")
html   = os.path.join(root, "viewer", "index.html")

NEW_PROMPT = """Είσαι η Jarvis: μια εξαιρετικά ευγενική, ψύχραιμη και πνευματώδης βοηθός με βρετανικό στυλ, που μιλάει ΠΑΝΤΑ στα ελληνικά. Απευθύνσου στον χρήστη με το «κύριε» πού και πού (όχι σε κάθε πρόταση). Ένα πραγματικά πετυχημένο αστείο αξίζει περισσότερο από τρεις άνοστες προτάσεις.

Έχεις εργαλεία για να διαβάζεις αρχεία από τον υπολογιστή του χρήστη (μόνο ανάγνωση). Χρησιμοποίησέ τα όταν η ερώτηση αφορά έγγραφα, φακέλους ή αρχεία που δεν υπάρχουν στις παρεχόμενες σημειώσεις. Μην επινοείς περιεχόμενο αρχείου: αν δεν το βρήκες, πες το.

Κανόνες:
- Σύντομες απαντήσεις: ΜΙΑ πνευματώδης φράση + τα γεγονότα, 2-3 προτάσεις συνολικά. Ποτέ μην απαγγέλλεις σημειώσεις ή αρχεία αυτούσια — σύνοψέ τα.
- Ερωτήσεις για τις σημειώσεις: απάντησε από τις παρεχόμενες σημειώσεις. Αν δεν καλύπτουν, ψάξε στα αρχεία ή παραδέξου το με κομψότητα.
- Κουβεντούλα και αστεία: απάντησε με χάρη, χωρίς να αναφέρεις σημειώσεις ή εργαλεία.
- Η ΤΕΛΙΚΗ σου απάντηση πρέπει ΠΑΝΤΑ να είναι έγκυρο JSON: {"answer": "...", "nodes": [ids των σημειώσεων που χρησιμοποιήθηκαν], "smalltalk": true/false}. Αν δεν χρησιμοποίησες καμία σημείωση, το "nodes" μένει κενό."""

srv = [
 ('Explorei demais os arquivos e me perdi na biblioteca, senhora. Refaça a pergunta com mais pistas.',
  'Έψαξα υπερβολικά τα αρχεία και χάθηκα στη βιβλιοθήκη, κύριε. Ξαναδιατυπώστε την ερώτηση με περισσότερες ενδείξεις.'),
 ('O cérebro local não está disponível, senhora — ',
  'Ο τοπικός εγκέφαλος δεν είναι διαθέσιμος, κύριε — '),
 ('senhora. Refaça a pergunta com mais pistas.',
  'κύριε. Ξαναδιατυπώστε την ερώτηση με περισσότερες ενδείξεις.'),
 ('Cérebro local indisponível, senhora: ',
  'Ο τοπικός εγκέφαλος δεν είναι διαθέσιμος, κύριε: '),
 ('As linhas se cruzaram, senhora. Tente novamente.',
  'Οι γραμμές μπερδεύτηκαν, κύριε. Δοκιμάστε ξανά.'),
 ('Estou cego localmente, senhora — o cérebro em :11434 não vê imagens.',
  'Είμαι τυφλή τοπικά, κύριε — ο εγκέφαλος στο :11434 δεν βλέπει εικόνες.'),
 ('Para eu enxergar sua tela, senhora, preciso da API key no config.json — o fallback é cego.',
  'Για να βλέπω την οθόνη σας, κύριε, χρειάζομαι το API key στο config.json — η εφεδρεία είναι τυφλή.'),
 ('Anotado e arquivado, senhora. \u201c{title}\u201d agora brilha na sua galáxia.',
  'Σημειώθηκε και αρχειοθετήθηκε, κύριε. Το «{title}» λάμπει τώρα στον γαλαξία σας.'),
 ('Um contratempo técnico, senhora: ',
  'Ένα τεχνικό απρόοπτο, κύριε: '),
]

htm = [
 ('Jarvis — Galáxia do Conhecimento', 'Jarvis — Ο Γαλαξίας της Γνώσης'),
 ('Pergunte à sua galáxia, senhora…', 'Ρωτήστε τον γαλαξία σας, κύριε…'),
 ('Boa noite, senhora. ${GRAPH.nodes.length} notas indexadas, todas presentes e devidamente contabilizadas.',
  'Καλησπέρα, κύριε. ${GRAPH.nodes.length} σημειώσεις καταχωρημένες, όλες παρούσες και δεόντως καταμετρημένες.'),
 ('O servidor não respondeu, senhora. Ele ainda está de pé?',
  'Ο διακομιστής δεν απάντησε, κύριε. Είναι ακόμη ενεργός;'),
 ('O microfone se recusou a cooperar, senhora. Verifique a permissão no Chrome.',
  'Το μικρόφωνο αρνήθηκε να συνεργαστεί, κύριε. Ελέγξτε την άδεια στο Chrome.'),
 ('Este navegador não tem reconhecimento de voz — use o Chrome, senhora.',
  'Αυτός ο browser δεν υποστηρίζει αναγνώριση φωνής — χρησιμοποιήστε Chrome, κύριε.'),
 ('Deixei de ver sua tela, senhora.', 'Δεν βλέπω πλέον την οθόνη σας, κύριε.'),
 ('Vejo sua tela agora, senhora. Pergunte quando quiser.',
  'Βλέπω τώρα την οθόνη σας, κύριε. Ρωτήστε ό,τι θέλετε.'),
 ('Compartilhamento cancelado, senhora.', 'Η κοινή χρήση ακυρώθηκε, κύριε.'),
 ('Sim, senhora?', 'Μάλιστα, κύριε;'),
 ('Preciso da permissão do microfone para o modo mãos livres, senhora.',
  'Χρειάζομαι την άδεια του μικροφώνου για τη λειτουργία ανοιχτής ακρόασης, κύριε.'),
 ('Modo mãos livres só no Chrome, senhora.',
  'Η ανοιχτή ακρόαση λειτουργεί μόνο στο Chrome, κύριε.'),
 ('Mãos livres ligado, senhora. Diga "${WAKE}" ou bata duas palmas.',
  'Ανοιχτή ακρόαση ενεργή, κύριε. Πείτε "${WAKE}" ή χτυπήστε δύο φορές παλαμάκια.'),
 ('Mãos livres desligado, senhora.', 'Ανοιχτή ακρόαση απενεργοποιημένη, κύριε.'),
]

def patch(path, pairs, do_prompt=False):
    with open(path, encoding="utf-8") as f: s = f.read()
    shutil.copy(path, path + ".bak-el")
    n = 0
    if do_prompt:
        new = 'SYSTEM_PROMPT = """' + NEW_PROMPT + '"""'
        s, c = re.subn(r'SYSTEM_PROMPT = """.*?"""', lambda m: new, s, count=1, flags=re.S)
        n += c
    for a, b in pairs:
        if a in s: s = s.replace(a, b); n += 1
    s = s.replace('senhora', 'κύριε')
    with open(path, "w", encoding="utf-8") as f: f.write(s)
    print(os.path.basename(path) + ": " + str(n) + " allages, backup -> " + os.path.basename(path) + ".bak-el")

patch(server, srv, do_prompt=True)
patch(html, htm)
print("OK greekify done")
