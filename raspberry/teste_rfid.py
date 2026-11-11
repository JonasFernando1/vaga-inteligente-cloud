
from mfrc522 import SimpleMFRC522
from time import sleep

leitor = SimpleMFRC522()

print("================================")
print("   TESTE RFID - VAGA INTELIGENTE")
print("================================")
print("Aproxime um cartao do leitor RC522")
print("Pressione Ctrl+C para encerrar\n")

try:
    while True:
        uid = leitor.read_id_no_block()

        if uid is not None:
            print(
                f"Cartao detectado! UID: {uid}",
                flush=True
            )

            # Evita repetir a leitura imediatamente
            sleep(2)

        sleep(0.2)

except KeyboardInterrupt:
    print("\nLeitura encerrada.")

finally:
    try:
        import RPi.GPIO as GPIO
        GPIO.cleanup()
    except ImportError:
        pass
