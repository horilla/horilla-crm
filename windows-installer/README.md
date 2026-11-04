# Horilla-CRM Windows Installer

This directory contains the complete Windows installer infrastructure for Horilla-CRM, including NSIS installer script, Windows service integration, and management tools.

## Overview

The Windows installer provides:
- **Automated Installation**: One-click setup with dependency management
- **Windows Service**: Background operation with automatic startup
- **Management Tools**: Batch scripts for administration and control
- **System Integration**: Start Menu shortcuts and desktop integration
- **Security**: Runs as dedicated service with proper permissions

## Prerequisites

### For Building the Installer:
- **NSIS (Nullsoft Scriptable Install System)**: Download from https://nsis.sourceforge.io/
- **Windows 10 or later** (64-bit)
- **Administrator privileges** for building and testing

### For Target Systems:
- **Windows 10 or later** (64-bit)
- **Python 3.12+** (installer can download if missing)
- **Administrator privileges** for service installation
- **2GB+ free disk space**

## Building the Installer

### Method 1: Automated Build
```batch
cd windows-installer
build-installer.bat
```

### Method 2: Manual Build
```batch
cd windows-installer
makensis horilla-crm-installer.nsi
```

## Installation Structure

### Installation Directories:
- **Application**: `C:\Program Files\Horilla-CRM\`
- **Configuration**: `%APPDATA%\Horilla-CRM\config\`
- **Data**: `%APPDATA%\Horilla-CRM\data\`
- **Logs**: `%APPDATA%\Horilla-CRM\logs\`
- **Media Files**: `%APPDATA%\Horilla-CRM\media\`

### Installed Components:
- Core Horilla-CRM application
- Python virtual environment with dependencies
- Windows service wrapper
- Management batch scripts
- Configuration files
- Start Menu shortcuts

## Management Scripts

### Core Scripts:
- **`horilla-crm-start.bat`**: Start the application server
- **`horilla-crm-stop.bat`**: Stop the application server
- **`horilla-crm-admin.bat`**: Administration interface
- **`setup-environment.bat`**: Environment setup (auto-run during install)

### Service Management:
- **`install-service.bat`**: Install as Windows service
- **`uninstall-service.bat`**: Remove Windows service

### Service Features:
- **Automatic Startup**: Starts with Windows
- **Background Operation**: Runs without user login
- **Crash Recovery**: Automatic restart on failure
- **Logging**: Comprehensive error and access logs
- **Security**: Runs with minimal privileges

## Configuration

### Main Configuration File:
`%APPDATA%\Horilla-CRM\config\horilla-crm.conf`

Key settings:
```ini
# Security
SECRET_KEY=auto-generated-key
DEBUG=0

# Network
ALLOWED_HOSTS=localhost,127.0.0.1
CSRF_TRUSTED_ORIGINS=http://localhost:8000

# Database (examples)
# SQLite (default):
DATABASE_URL=sqlite:///C:/Users/{user}/AppData/Roaming/Horilla-CRM/data/horilla.db

# PostgreSQL:
DATABASE_URL=postgres://username:password@localhost:5432/horilla_crm

# MySQL:
DATABASE_URL=mysql://username:password@localhost:3306/horilla_crm
```

## Usage Instructions

### After Installation:

1. **First-time Setup**:
   ```batch
   # Create administrative user
   "C:\Program Files\Horilla-CRM\scripts\horilla-crm-admin.bat"
   # Choose option 1: Create superuser
   ```

2. **Start Application**:
   - **Manual**: Use Start Menu → Horilla-CRM
   - **Service**: Automatic startup (if service installed)
   - **URL**: http://localhost:8000

3. **Administration**:
   ```batch
   # Open admin interface
   "C:\Program Files\Horilla-CRM\scripts\horilla-crm-admin.bat"
   ```

4. **Service Management**:
   ```batch
   # Install service (requires admin)
   "C:\Program Files\Horilla-CRM\scripts\install-service.bat"

   # Control via Windows services or:
   net start HorillaCRM
   net stop HorillaCRM
   ```

## Database Setup

### SQLite (Default):
- **Auto-configured**: Works out of the box
- **Location**: `%APPDATA%\Horilla-CRM\data\horilla.db`
- **Good for**: Testing, small deployments

### PostgreSQL (Recommended for Production):
1. Install PostgreSQL
2. Create database and user:
   ```sql
   CREATE DATABASE horilla_crm;
   CREATE USER horilla_user WITH PASSWORD 'secure_password';
   GRANT ALL PRIVILEGES ON DATABASE horilla_crm TO horilla_user;
   ```
3. Update configuration:
   ```ini
   DATABASE_URL=postgres://horilla_user:secure_password@localhost:5432/horilla_crm
   ```

### MySQL:
1. Install MySQL/MariaDB
2. Create database and user:
   ```sql
   CREATE DATABASE horilla_crm;
   CREATE USER 'horilla_user'@'localhost' IDENTIFIED BY 'secure_password';
   GRANT ALL PRIVILEGES ON horilla_crm.* TO 'horilla_user'@'localhost';
   ```
3. Update configuration:
   ```ini
   DATABASE_URL=mysql://horilla_user:secure_password@localhost:3306/horilla_crm
   ```

## Web Server Integration

### IIS Integration:
1. Install IIS with CGI support
2. Install Python CGI handler
3. Configure virtual directory pointing to Horilla-CRM

### Nginx for Windows:
1. Download Nginx for Windows
2. Configure reverse proxy:
   ```nginx
   server {
       listen 80;
       server_name localhost;

       location / {
           proxy_pass http://127.0.0.1:8000;
           proxy_set_header Host $host;
           proxy_set_header X-Real-IP $remote_addr;
           proxy_set_header X-Forwarded-For $remote_addr;
       }
   }
   ```

## Security Considerations

### Firewall:
- **Default**: Only localhost access (127.0.0.1:8000)
- **Production**: Configure Windows Firewall for external access
- **HTTPS**: Use reverse proxy (IIS/Nginx) for SSL termination

### User Permissions:
- **Service**: Runs as LocalService account
- **Files**: Application files read-only, data files writable
- **Network**: Bound to localhost by default

### Hardening:
- Set a unique `SECRET_KEY` (a shipped placeholder is ignored; with Redis unset, run one worker or the login counter is per process)
- Set `TRUSTED_PROXIES=127.0.0.1` when a reverse proxy on this machine sets the client IP
- Use strong database passwords
- Enable HTTPS in production
- Regular security updates

## Troubleshooting

### Installation Issues:
1. **Permission Denied**: Run installer as Administrator
2. **Python Not Found**: Install Python 3.12+ manually
3. **Port 8000 in Use**: Change port in configuration or stop conflicting service

### Service Issues:
1. **Service Won't Start**: Check Windows Event Viewer
2. **Database Errors**: Verify database configuration and connectivity
3. **Permission Errors**: Ensure service has proper file permissions

### Application Issues:
1. **Can't Access Web Interface**: Check if server is running on correct port
2. **Static Files Missing**: Run `collectstatic` command via admin interface
3. **Database Migration Errors**: Run migrations via admin interface

### Log Files:
- **Application Logs**: `%APPDATA%\Horilla-CRM\logs\`
- **Service Logs**: Windows Event Viewer → Applications and Services
- **Web Server Logs**: Access and error logs in logs directory

## File Structure

```
windows-installer/
├── horilla-crm-installer.nsi     # Main NSIS installer script
├── build-installer.bat           # Automated build script
├── scripts/                      # Management scripts
│   ├── horilla_service.py        # Windows service wrapper
│   ├── setup-environment.bat     # Environment setup
│   ├── horilla-crm-start.bat     # Start application
│   ├── horilla-crm-stop.bat      # Stop application
│   ├── horilla-crm-admin.bat     # Admin interface
│   ├── install-service.bat       # Install service
│   └── uninstall-service.bat     # Remove service
├── config/                       # Configuration files
│   ├── horilla-crm.conf          # Main configuration
│   ├── logging.conf              # Logging configuration
│   └── requirements-windows.txt  # Windows-specific dependencies
├── icons/                        # Application icons (add custom)
├── resources/                    # Installer resources
└── README.md                     # This file
```

## Distribution

### Signing the Installer:
For production distribution, sign the installer with a code signing certificate:
```batch
signtool sign /f certificate.pfx /p password /t http://timestamp.digicert.com Horilla-CRM-1.0.0-Setup.exe
```

### Deployment Options:
1. **Direct Distribution**: Share the .exe file
2. **Group Policy**: Deploy via Windows Group Policy
3. **SCCM**: Deploy via System Center Configuration Manager
4. **Chocolatey**: Create Chocolatey package for easy updates

## Support

- **Documentation**: Available in installed application
- **GitHub**: https://github.com/horilla-opensource/horilla-crm
- **Issues**: Use GitHub issue tracker
- **Community**: Check project documentation for community resources

---

**Note**: This installer is designed for Windows environments. For Linux deployment, use the Debian package in the `debian/` directory.
