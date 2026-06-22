# TeeBotus SELinux Doctor

`audit2allow -c systemd` ist fuer TeeBotus meistens der falsche Reflex. Der Filter schaut nur auf `comm=systemd`; echte Denials koennen von `python`, `secret-tool`, `podman`, `qdrant` oder falschen Dateilabels kommen. Signal-Rohlogs wie `INFO [Raw Message] {"envelope": ...}` sind keine SELinux-AVCs.

Der sichere Pfad ist:

```bash
teebotus-selinux-doctor
```

Der Doctor prueft standardmaessig zuerst User-systemd und danach System-systemd. Das ist wichtig, weil TeeBotus hier als User-Unit laufen kann. Bei Bedarf kann der Scope explizit gesetzt werden:

```bash
teebotus-selinux-doctor --unit-scope user
teebotus-selinux-doctor --unit-scope system
```

Ohne Root ist die Ausgabe absichtlich defensiv: Der SELinux-Modulstore ist auf Fedora normalerweise nicht lesbar. Fuer eine echte Modulpruefung:

```bash
sudo teebotus-selinux-doctor
```

Wenn der Root-Lauf fuer eine spaetere Pruefung belegbar sein soll:

```bash
sudo teebotus-selinux-doctor --format json --output /home/teladi/Downloads/teebotus-selinux-doctor-root.json
```

Verdächtige Panikmodule werden nur gemeldet, nicht entfernt. Entfernen ist ein expliziter Schritt:

```bash
sudo teebotus-selinux-doctor --remove-suspect --apply
```

Fuer einen ganz bestimmten Modulnamen:

```bash
sudo teebotus-selinux-doctor --module my-systemd --apply
```

Der Doctor entfernt keine generischen oder unbekannten `systemd`-Module automatisch. Module, die nur nach manueller Pruefung entfernt werden sollten, werden separat als `Manuell pruefen` gelistet.
