import asyncio

from eqemu_sso_login_proxy import server

if __name__ == '__main__':
    loop = asyncio.get_event_loop()
    loop.create_task(server.main())
    try:
        loop.run_forever()
    except KeyboardInterrupt:
        pass
    print("Shutting down.")
    loop.close()
