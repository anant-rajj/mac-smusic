CC=swiftc
CFLAGS=-O
BIN=bin/mac-smusic-engine
SRC=src/native/engine.swift

all: $(BIN)

$(BIN): $(SRC)
	@mkdir -p bin
	$(CC) $(CFLAGS) $(SRC) -o $(BIN)
	@echo "Build complete: $(BIN)"

clean:
	rm -rf bin/mac-smusic-engine

install: $(BIN)
	cp $(BIN) /usr/local/bin/ || cp $(BIN) $(HOME)/.local/bin/

.PHONY: all clean install
