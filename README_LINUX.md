# P99 Login Proxy - Linux Setup Guide

This guide will help you set up and run the P99 Login Proxy application on Linux systems.

## Prerequisites

- git
- python3.11 or higher
- virtualenv (recommended)

## Installation Steps

### 1. Clone the Repository

```bash
git clone https://github.com/eq-p99-tools/p99-login-proxy.git ~/p99-login-proxy
```

### 2. Create and Activate a Virtual Environment

```bash
python3 -m venv ~/p99-login-proxy/.venv
source ~/p99-login-proxy/.venv/bin/activate
```

### 3. Install the Application

```bash
source ~/p99-login-proxy/.venv/bin/activate
pip install -e ~/p99-login-proxy
```

Note: If you encounter issues installing wxPython, you may need to install build dependencies for it. See the [wxPython documentation](https://wxpython.org/pages/downloads/) for more information.

### 4. Run the Application

For now, you'll need to run the application from within your EverQuest directory.
If you followed the instructions in the previous step, the binary will be in your path as long as you've activated the virtual environment.

```bash
source ~/p99-login-proxy/.venv/bin/activate
cd $MY_EQ_DIRECTORY
p99loginproxy
```

## Troubleshooting

### Launch Everquest button not working

It's very likely this button will not work for you right now. There are a myriad of ways that EverQuest can be installed and configured, and the button is currently hardcoded to exactly one of them, so maybe you'll get lucky.

At the moment it simply runs `wine eqgame.exe patchme` from the working directory of the application. If there isn't a wine binary in your path, you could technically make a script with that name that runs the correct command for your system, and just ignore the args, and that would work. Note that the button is absolutely not required for the proxy to function.

## Support

If you encounter any issues, please open an issue on the [GitHub repository](https://github.com/eq-p99-tools/p99-login-proxy/issues) or reach out to @Toald in almost any of the Project 1999 related Discord servers.

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.
I appologize for how pedantic I may be during the review period. :)