
from gpiozero import DistanceSensor
from time import sleep

sensor = DistanceSensor(
    echo=24,
    trigger=23,
    max_distance=0.30,
    threshold_distance=0.05,
    queue_len=3
)

print("Teste do sensor de segurança da cancela")
print("Coloque um objeto a 3 a 5 cm do sensor.")
print("Ctrl+C para encerrar.\n")

try:
    while True:
        distancia = sensor.distance * 100

        if distancia <= 5:
            estado = "OBSTACULO DETECTADO"
        else:
            estado = "AREA LIVRE"

        print(
            f"Distancia: {distancia:.1f} cm "
            f"| {estado}",
            flush=True
        )

        sleep(0.3)

except KeyboardInterrupt:
    print("\nTeste encerrado.")

finally:
    sensor.close()

