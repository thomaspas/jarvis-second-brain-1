# ΤΑΥΤΟΤΗΤΑ ΜΗΧΑΝΗΜΑΤΟΣ — EVO-3 (READ FIRST, ΓΙΑ ΚΑΘΕ AI)

> Κάθε AI/agent που δουλεύει σε αυτό το project πρέπει να ξέρει ΑΚΡΙΒΩΣ σε τι
> μηχάνημα τρέχει ο Jarvis και πώς λειτουργεί. Επαληθευμένο live (2026-09-02:
> `cat /etc/os-release`, `uname -a`, `lspci`, `systemctl`). Μιλάμε ΕΛΛΗΝΙΚΑ.

## Hardware
- **GMKtec EVO-X3** mini-PC — AMD Ryzen AI APU (Strix Halo class), ενσωματωμένη
  Radeon GPU (PCI id `1586`). Επιλέχθηκε ειδικά για **τοπικό AI** χωρίς ξεχωριστή
  κάρτα γραφικών. Το APU τρέχει το 27B μοντέλο μέσω **llama.cpp Vulkan**.

## Λειτουργικό
- **Ubuntu 24.04.4 LTS (Noble Numbat)** — στάνταρ Ubuntu, ΟΧΙ εξωτικό distro, αλλά
  στημένο ως **AI server**, γι' αυτό «ιδιαίτερο» στην πράξη:
- **ΓΡΑΦΙΚΟ ΠΕΡΙΒΑΛΛΟΝ:** τρέχει GNOME Shell (Wayland) + xrdp στο `:3389`. Η παλιά σημείωση περί HEADLESS ήταν λάθος — ο browser δουλεύει μέσω RDP. Το `desktop/jarvis.py` (GTK/QT) παραμένει ριψοκίνδυνο εδώ· για καθημερινή χρήση προτιμάμε τη **web** έκδοση.
- **Kernel 7.0.0-30-generic** — πολύ νεότερος από τον στάνταρ 6.8 του 24.04
  (υποστήριξη του φρέσκου AMD hardware).
- **Vulkan:** ο driver δουλεύει (το `:11434` απαντά)· λείπει μόνο το εργαλείο
  διαγνωσης `vulkan-tools` (`vulkaninfo`).

## Ιδιωτικότητα — ΜΗΔΕΝΙΚΗ τηλεμετρία (σκόπιμα)
- `ubuntu-report`=not-found, `whoopsie`=not-found/inactive, `apport`=**masked**,
  `motd-news`=χωρίς config, `popcon`=not installed. Τίποτα δεν φεύγει προς Canonical.
- Συνδυασμένο με τον τοπικό εγκϬφαλο κανένα cloud API) = πλήρως αυτόνομο/ιδιωτικό AI.

## Δικτύωση & υπηρεσίες
- LAN IP `192.168.1.9`. SSH ενεργό (μπαίνει π.χ. από Gaming-7).
- **Galaxy** `jarvis-galaxy.service` → `server.py` σε `127.0.0.1:4700` (loopback, βλ. JARVIS_BIND) (σερβίρει HUD +
  viewer/, endpoints `/chat`, `/remember`, `/api/home`, `/health`, `/settings`).
- **Brain** `llama-server.service` → llama.cpp Vulkan σε `127.0.0.1:11434`.
- Και τα δύο `Restart=always` + `enabled` → reboot-safe & crash-safe (M2 done).
- Υγεία με μια ματιά: `GET /health` → `{status, brain_up, model, notes_count}`.
- **Bind policy (2026-09-03):** `4700` και `11434` ΜΟΝΟ σε `127.0.0.1`. Από άλλο μηχάνημα: ssh tunnel ή `tailscale serve` — ΠΟΤΕ `0.0.0.0`. Override: `JARVIS_BIND` env var + `LLM_HOST` στο drop-in `bind.conf`.

## Κανόνες για κάθε AI
- ΔΕΝ έχεις SSH. ΟΛΕΣ οι εντολές τρέχουν ΑΠΟ τον χρήστη πάνω στο EVO-3.
- Το prompt του πρέπει να λέει `thomas-pashoulas@thomas-pashoulas-EVO-X3` — ΟΧΙ
  `thomas1821@...-Gaming-7` (ΑΛΛΟ μηχάνημα, χωρίς Jarvis).
- Read-only στο live μηχάνημα· καμία διαγραφή/αλλαγή secrets· ποτέ μην τυπώνεις
  API keys/κλειδιά/hostnames. Reliability first. Αναστρέψιμα > μόνιμα.
