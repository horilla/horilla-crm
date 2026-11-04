# Horilla-CRM Debian Package

This directory contains the Debian packaging configuration for Horilla-CRM.

## Package Information

- **Package Name**: horilla-crm
- **Version**: 1.0.0-1
- **Architecture**: all
- **License**: LGPL-2.1+
- **Maintainer**: Horilla CRM Team <support@horilla.com>

## Installation Locations

- **Application**: `/opt/horilla-crm/`
- **Configuration**: `/etc/horilla-crm/`
- **Data**: `/var/lib/horilla-crm/`
- **Logs**: `/var/log/horilla-crm/`
- **Service**: `systemd` (horilla-crm.service)
- **User**: `horilla-crm` (system user)

## Building the Package

### Prerequisites (Ubuntu/Debian)

```bash
sudo apt-get install dpkg-dev debhelper python3-dev python3-venv \
                     build-essential libjpeg-dev zlib1g-dev \
                     libfreetype6-dev liblcms2-dev libopenjp2-7-dev \
                     libwebp-dev libpq-dev
```

### Build Process

```bash
# Method 1: Use the build script
./debian/build-package.sh

# Method 2: Manual build
dpkg-buildpackage -us -uc -b
```

## Installation

```bash
# Install the package
sudo dpkg -i ../horilla-crm_*.deb

# Fix any dependency issues
sudo apt-get install -f
```

## Configuration

1. **Edit configuration file**:
   ```bash
   sudo nano /etc/horilla-crm/horilla-crm.conf
   ```

2. **Key settings to update**:
   - `SECRET_KEY`: Auto-generated, but can be changed
   - `DEBUG`: Set to 0 for production
   - `ALLOWED_HOSTS`: Add your domain/IP
   - `DATABASE_URL`: Configure your database connection

3. **Database setup** (if using PostgreSQL):
   ```bash
   # Create database and user
   sudo -u postgres psql
   CREATE DATABASE horilla_crm;
   CREATE USER horilla_user WITH PASSWORD 'your_password';
   GRANT ALL PRIVILEGES ON DATABASE horilla_crm TO horilla_user;
   \\q

   # Update configuration
   echo "DATABASE_URL=postgres://horilla_user:your_password@localhost/horilla_crm" >> /etc/horilla-crm/horilla-crm.conf
   ```

4. **Create superuser**:
   ```bash
   sudo -u horilla-crm horilla-crm-manage createsuperuser
   ```

## Service Management

```bash
# Start the service
sudo systemctl start horilla-crm

# Enable automatic startup
sudo systemctl enable horilla-crm

# Check status
sudo systemctl status horilla-crm

# View logs
sudo journalctl -u horilla-crm -f

# Restart service
sudo systemctl restart horilla-crm
```

## Management Commands

The package provides a wrapper script for Django management commands:

```bash
# General syntax
sudo -u horilla-crm horilla-crm-manage <command>

# Examples
sudo -u horilla-crm horilla-crm-manage migrate
sudo -u horilla-crm horilla-crm-manage collectstatic
sudo -u horilla-crm horilla-crm-manage createsuperuser
sudo -u horilla-crm horilla-crm-manage shell
```

## Web Server Configuration

### Nginx Example

```nginx
server {
    listen 80;
    server_name your-domain.com;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $remote_addr;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location /static/ {
        alias /opt/horilla-crm/staticfiles/;
        expires 1y;
        add_header Cache-Control "public, max-age=31536000, immutable";
    }
}
```

Leave `/media/` on the proxy to the application. Horilla serves uploads only after a login. Do not alias that URL to the media directory.

Set `TRUSTED_PROXIES=127.0.0.1` when nginx proxies to the app on localhost. Horilla ignores `X-Forwarded-For` from any other peer, so a client cannot pick a fresh lockout counter by changing that header.

## Package Files

- `control`: Package metadata and dependencies
- `rules`: Build instructions
- `compat`: Debhelper compatibility level
- `install`: File installation mapping
- `changelog`: Version history
- `copyright`: License information
- `postinst`: Post-installation script
- `prerm`: Pre-removal script
- `postrm`: Post-removal script
- `horilla-crm.service`: Systemd service file
- `horilla-crm.logrotate`: Log rotation configuration
- `build-package.sh`: Build automation script

## Troubleshooting

### Service won't start
```bash
# Check service status
sudo systemctl status horilla-crm

# Check logs
sudo journalctl -u horilla-crm -n 50

# Check configuration
sudo -u horilla-crm horilla-crm-manage check
```

### Database issues
```bash
# Run migrations
sudo -u horilla-crm horilla-crm-manage migrate

# Check database connection
sudo -u horilla-crm horilla-crm-manage dbshell
```

### Permission issues
```bash
# Fix ownership
sudo chown -R horilla-crm:horilla-crm /opt/horilla-crm
sudo chown -R horilla-crm:horilla-crm /var/lib/horilla-crm
sudo chown -R horilla-crm:horilla-crm /var/log/horilla-crm
```

## Uninstallation

```bash
# Remove package (keep data)
sudo apt-get remove horilla-crm

# Complete removal (including data)
sudo apt-get purge horilla-crm
sudo rm -rf /var/lib/horilla-crm /var/log/horilla-crm
```

## Development

To modify the package:

1. Update version in `debian/changelog`
2. Modify configuration in relevant files
3. Test build: `./debian/build-package.sh`
4. Test installation in a clean environment

## Support

- GitHub: https://github.com/horilla-opensource/horilla-crm
- Documentation: Available in the application
- Issues: Use GitHub issue tracker
