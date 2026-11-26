# Yume 2kki OSS — build & extraction pipeline
#
#   make extract   extract original/ into build/game + xml/   (needs lcf2xml)
#   make data      rebuild build/game LCF from edited xml/
#   make player    build EasyRPG Player into build/player
#   make run       run the game from build/game
#   make verify    sanity-check the extracted tree
#   make audit     resolve every asset reference, report missing/unused
#   make map-tree  analyse/prune the map tree (report only)
#   make prune-tree apply the pruned map tree and rebuild RPG_RT.lmt
#   make translate generate translation/<lang>/*.po (EasyRPG Player)
#   make run-en    run the game with the English translation
#   make clean     remove build/ and xml/
#
# Everything is derived from original/ which is read-only and never modified.

SHELL   := /bin/bash
PYTHON  ?= python3
JOBS    ?= $(shell nproc 2>/dev/null || echo 4)

BUILD   ?= build
GAME    ?= $(BUILD)/game
XML     ?= xml
PREFIX  ?= $(BUILD)/prefix
TRANSLATION ?= translation
TR_LANG ?= en

LCF2XML        ?= $(BUILD)/liblcf/lcf2xml
PLAYER         ?= $(BUILD)/player/easyrpg-player
LIBLCF_CONFIG  ?= $(PREFIX)/lib/cmake/liblcf/liblcf-config.cmake

CMAKE_FLAGS := -G Ninja -DCMAKE_BUILD_TYPE=Release

.PHONY: all extract xml data player run run-en verify audit map-tree prune-tree translate clean distclean help

all: extract

help:
	@sed -n '1,13p' Makefile | sed 's/^# \{0,1\}//'

# ---------------------------------------------------------------- liblcf ---
$(LCF2XML):
	@mkdir -p $(BUILD)
	cmake -S vendor/liblcf -B $(BUILD)/liblcf $(CMAKE_FLAGS) \
		-DBUILD_SHARED_LIBS=OFF \
		-DLIBLCF_ENABLE_TESTS=OFF \
		-DLIBLCF_ENABLE_BENCHMARKS=OFF \
		-DLIBLCF_ENABLE_INSTALL=ON \
		-DCMAKE_INSTALL_PREFIX=$(abspath $(PREFIX))
	cmake --build $(BUILD)/liblcf --target lcf2xml -j$(JOBS)

$(LIBLCF_CONFIG): $(LCF2XML)
	cmake --build $(BUILD)/liblcf --target install -j$(JOBS)

# --------------------------------------------------------------- extract ---
extract: $(LCF2XML)
	$(PYTHON) scripts/extract.py \
		--src original --game $(GAME) --xml $(XML) --lcf2xml $(LCF2XML)

# only refresh XML from an already-extracted game dir
xml: $(LCF2XML)
	$(PYTHON) scripts/extract.py \
		--src original --game $(GAME) --xml $(XML) --lcf2xml $(LCF2XML) \
		--force-xml

# ---------------------------------------------------------------- data ---
data: $(LCF2XML)
	$(PYTHON) scripts/rebuild.py --xml $(XML) --game $(GAME) --lcf2xml $(LCF2XML)

# ---------------------------------------------------------------- player ---
$(PLAYER): $(LIBLCF_CONFIG)
	cmake -S vendor/Player -B $(BUILD)/player $(CMAKE_FLAGS) \
		-DCMAKE_PREFIX_PATH=$(abspath $(PREFIX)) \
		-DPLAYER_TARGET_PLATFORM=SDL2 \
		-DPLAYER_BUILD_LIBLCF=OFF \
		-DPLAYER_ENABLE_TESTS=OFF
	cmake --build $(BUILD)/player -j$(JOBS)

player: $(PLAYER)

run: extract $(PLAYER)
	$(PLAYER) --game $(GAME)

# ----------------------------------------------------------- translation ---
translate: extract
	$(PYTHON) scripts/translate.py --xml $(XML) --out $(TRANSLATION) --lang $(TR_LANG)

run-en: extract translate $(PLAYER)
	$(PLAYER) --game $(GAME) --language-path $(TRANSLATION) --language $(TR_LANG)

# ---------------------------------------------------------------- verify ---
verify: extract
	$(PYTHON) scripts/verify.py --game $(GAME) --xml $(XML)

# ---------------------------------------------------------------- audit ---
audit: extract
	$(PYTHON) scripts/audit.py --game $(GAME) --xml $(XML)

# ------------------------------------------------------------- map tree ---
map-tree: extract
	$(PYTHON) scripts/map_tree.py --lmt $(XML)/RPG_RT.emt --game $(GAME)

prune-tree: $(LCF2XML)
	$(PYTHON) scripts/map_tree.py --lmt $(XML)/RPG_RT.emt --game $(GAME) --apply
	$(PYTHON) scripts/rebuild.py --xml $(XML) --game $(GAME) --lcf2xml $(LCF2XML)

# ----------------------------------------------------------------- clean ---
clean:
	rm -rf $(BUILD) $(XML)

distclean: clean
	rm -rf vendor/Player/lib
