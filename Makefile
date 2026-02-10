.PHONY: demo test install lint format clean help

# Delegate all targets to chart_module/Makefile
demo test install lint format clean help:
	$(MAKE) -C chart_module $@
