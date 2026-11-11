"""Cadastro local de cartão no SQLite. Uso: python cadastrar_cartao.py UID 'Nome'."""
import argparse
from banco import cadastrar_cartao, inicializar_banco, verificar_cartao


def main():
    parser = argparse.ArgumentParser(description="Cadastrar/autorizar cartão RC522")
    parser.add_argument("uid", help="Identificador decimal do cartão, sem espaços")
    parser.add_argument("nome", help="Nome exibido no dashboard")
    parser.add_argument("--negar", action="store_true", help="Marcar cartão como não autorizado")
    args = parser.parse_args()
    if not args.uid.isdigit():
        parser.error("UID deve conter apenas dígitos")
    inicializar_banco()
    cadastrar_cartao(args.uid, args.nome, autorizado=not args.negar)
    registro = verificar_cartao(args.uid)
    print("Cartão salvo:", registro)


if __name__ == "__main__":
    main()
