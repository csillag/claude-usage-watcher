PYTHON ?= python3
INSTALL_DIR ?= $(HOME)/local/bin

.PHONY: test install clean

test:
	$(PYTHON) -m unittest discover -s tests -v

install: bin/claude-usage
	mkdir -p $(INSTALL_DIR)
	cp bin/claude-usage $(INSTALL_DIR)/claude-usage
	chmod +x $(INSTALL_DIR)/claude-usage
	@echo "Installed to $(INSTALL_DIR)/claude-usage"

clean:
	find . -name __pycache__ -type d -exec rm -rf {} +
	find . -name '*.pyc' -delete
