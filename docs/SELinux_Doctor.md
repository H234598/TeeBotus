# TeeBotus SELinux Doctor

`audit2allow -c systemd` ist fuer TeeBotus meistens der falsche Reflex. Der Filter schaut nur auf `comm=systemd`; echte Denials koennen von `python`, `secret-tool`, `podman`, `qdrant` oder falschen Dateilabels kommen. Signal-Rohlogs wie `INFO [Raw Message] {"envelope": ...}` sind keine SELinux-AVCs.

Der sichere Pfad ist:

```bash
teebotus-selinux-doctor
```

Ohne Root ist die Ausgabe absichtlich defensiv: Der SELinux-Modulstore ist auf Fedora normalerweise nicht lesbar. Fuer eine echte Modulpruefung:

```bash
sudo teebotus-selinux-doctor
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
