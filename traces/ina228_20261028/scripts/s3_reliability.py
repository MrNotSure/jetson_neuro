# Step 3: I2C reliability. 10,000 reads of MANUFACTURER_ID at each frequency.
N = 10_000
buf = bytearray(2)
results = []
for f in (100_000, 400_000, 1_000_000):
    i2c = bus(f)
    errs = {}
    wrong = 0
    wrong_examples = []
    t0 = time.ticks_us()
    for i in range(N):
        try:
            i2c.readfrom_mem_into(ADDR, MANUFACTURER_ID, buf)
            if buf[0] != 0x54 or buf[1] != 0x49:
                wrong += 1
                if len(wrong_examples) < 5:
                    wrong_examples.append((i, bytes(buf)))
        except OSError as e:
            k = e.args[0]
            errs[k] = errs.get(k, 0) + 1
    dt = time.ticks_diff(time.ticks_us(), t0)
    print("RELIABILITY req=%d bus=%s reads=%d exceptions=%s wrong=%d examples=%s total_us=%d us_per_read=%.1f"
          % (f, i2c, N, errs, wrong, wrong_examples, dt, dt / N))
    results.append((f, sum(errs.values()), wrong))
    # Bus still healthy at 100 kHz afterwards?
    chk = bus(100_000)
    print("  check at 100 kHz afterwards: scan %s, IDs %s" % (chk.scan(), ["0x%04X" % x for x in check_ids(chk)]))
    if f == 100_000 and (sum(errs.values()) or wrong):
        print("STOP: errors at 100 kHz")
        break

ok = [f for f, e, w in results if e == 0 and w == 0]
print("zero-error frequencies:", ok)
ina_reset(bus(100_000))
print("INA228 reset")
