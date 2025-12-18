# qx-l2 Documentation

Complete documentation for the standalone L2 order book data collector.

## Documentation Index

### Getting Started
- **[User Guide](USER_GUIDE.md)** - Complete user guide with examples
- **[Run Instructions](RUN_INSTRUCTIONS.md)** - Step-by-step setup and operation
- **[Configuration Reference](CONFIGURATION.md)** - All configuration options

### Technical Documentation  
- **[Architecture](ARCHITECTURE.md)** - System design and technical details
- **[Main README](../README.md)** - Package overview and quick start

## Quick Navigation

### For New Users
1. Start with [Run Instructions](RUN_INSTRUCTIONS.md) for step-by-step setup
2. Read [User Guide](USER_GUIDE.md) for comprehensive usage examples
3. Customize [Configuration](CONFIGURATION.md) for your needs

### For Developers
1. Review [Architecture](ARCHITECTURE.md) for system design
2. Check [Configuration Reference](CONFIGURATION.md) for all options
3. See [Main README](../README.md) for API examples

### For Operations
1. Use [Run Instructions](RUN_INSTRUCTIONS.md) for deployment
2. Follow [User Guide](USER_GUIDE.md) monitoring section
3. Reference [Configuration](CONFIGURATION.md) for tuning

## Key Features Documented

- **Independent Operation**: No dependencies on external systems
- **Symbol Selection**: 4 modes (static, rotating, hybrid, external)
- **System Tagging**: IBKR client separation (L2COLLECT_500)
- **Event Journaling**: Complete SQLite audit trail
- **Flexible Scheduling**: Configurable collection windows
- **ML Integration**: Export datasets for training
- **Production Ready**: Daemon mode, systemd service

## Support

- **Configuration Issues**: See [Configuration Reference](CONFIGURATION.md)
- **Connection Problems**: Check [Run Instructions](RUN_INSTRUCTIONS.md) troubleshooting
- **Data Quality**: Review [User Guide](USER_GUIDE.md) monitoring section
- **Architecture Questions**: Read [Architecture](ARCHITECTURE.md) design decisions
