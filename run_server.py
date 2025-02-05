import asyncio

from eqemu_sso_login_proxy import server

if __name__ == '__main__':
    asyncio.run(server.main())
