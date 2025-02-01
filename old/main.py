import connection


def print_error(errcode):
    print(f"Error: {errcode}")
    return errcode

def main():
    con = connection.Connection()
    try:
        connection.connection_open(con)
        while True:
            connection.connection_read(con)
    except Exception as e:
        connection.connection_close(con)
        return print_error(e.args[0])
    connection.connection_close(con)
    return 0


if __name__ == "__main__":
    main()
