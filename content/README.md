# Original content tracking

The base game XML is derived from `original/` and is **not** committed (the
assets and text are copyrighted). This directory carries only *our* changes:

```
content/baseline.json   hashes of the pristine extracted XML (committed once)
content/content.json    manifest of our edits (patches, new files, deletions)
content/patches/*.patch unified diffs for edited XML files
content/files/**        full XML for brand-new files
```

Baseline XML is regenerated on demand from `original/` via `lcf2xml` and
`build/manifest.json`; nothing multi-GB is committed or needed on disk.

`RPG_RT.emt` is excluded: the map-tree prune is tooling (`make prune-tree`),
not content. Map display names belong in the translation catalogue.

## One-time bootstrap

```sh
make extract
make prune-tree
make content-baseline   # hash the pristine xml/ (already committed)
make content-status     # should say 0 modified / 0 added / 0 deleted
```

`content/baseline.json` is what makes `status`/`export` possible. If you run
`make extract` later, re-run `make prune-tree` so the XML matches the baseline
(a normal extraction without the prune has the original 4601-node tree).

## Authoring loop

```sh
$EDITOR xml/Map0001.emu          # edit a map, the database, ...
make data                        # rebuild only edited LCF into build/game
make run                         # or make run-en
make content-status              # list M/A/D
make content-export              # write content/patches + content/files
git add content && git commit
```

`make content-export` produces unified diffs against the regenerated baseline
for `Map*.emu`, `RPG_RT.edb`, etc., and copies brand-new files in full.

## Collaborator loop

```sh
make extract
make prune-tree
make content-apply               # apply content/content.json to xml/
make data
make run-en
```

`make content-check` verifies that every exported patch still applies to its
regenerated baseline and reproduces the current XML exactly.

## Adding assets

New images/audio cannot be expressed as XML diffs. Put them under
`content/assets/<folder>/<file>` and reference them from the map/database like
any other asset. They are committed only if they are your own work or
permissively licensed. (A dedicated asset manifest can be added later.)

## Limits

- The tool tracks XML only. Binary `.lmu/.ldb/.lmt` edits are not tracked;
  always edit the XML and rebuild.
- Deleted base files are recorded and removed on `apply`.
- If a modified file has no manifest entry in `build/manifest.json` (new file),
  it is exported in full instead of as a diff.
