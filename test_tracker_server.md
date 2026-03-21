# Tracker Server — Testing Guide

## Setup

Make sure you're in the project directory and the server is stopped before each test run.
rm-rf the `torrents/` folder between runs to start clean.

---

## Test 1 — createtracker (success)

```bash
echo "<createtracker movie1.avi 109283519 Ghost_and_the_Darkness abc123 192.168.1.1 2097>" | nc localhost 6000
```

**Expected:**
```
<createtracker succ>
```

**Check the file was created:**
```bash
cat torrents/movie1.avi.track
```

**Expected file contents:**
```
Filename: movie1.avi
Filesize: 109283519
Description: Ghost_and_the_Darkness
MD5: abc123
#list of peers follows next
192.168.1.1:2097:0:109283519:<timestamp>
```

---

## Test 2 — createtracker (duplicate, should fail)

Run the exact same command again:

```bash
echo "<createtracker movie1.avi 109283519 Ghost_and_the_Darkness abc123 192.168.1.1 2097>" | nc localhost 6000
```

**Expected:**
```
<createtracker ferr>
```

---

## Test 3 — updatetracker (success)

Add a second peer to the same tracker file:

```bash
echo "<updatetracker movie1.avi 0 109283519 10.0.0.2 3000>" | nc localhost 6000
```

**Expected:**
```
<updatetracker movie1.avi succ>
```

**Check both peers are in the file:**
```bash
cat torrents/movie1.avi.track
```

**Expected — two peer lines at the bottom:**
```
192.168.1.1:2097:0:109283519:<timestamp>
10.0.0.2:3000:0:109283519:<timestamp>
```

---

## Test 4 — updatetracker (file does not exist)

```bash
echo "<updatetracker ghost.avi 0 5000 10.0.0.3 4000>" | nc localhost 6000
```

**Expected:**
```
<updatetracker ghost.avi ferr>
```

---

## Test 5 — REQ LIST

```bash
echo "<REQ LIST>" | nc localhost 6000
```

**Expected:**
```
<REP LIST 1>
<1 movie1.avi 109283519 abc123>
<REP LIST END>
```

**Add a second tracker file and test again:**
```bash
echo "<createtracker notes.txt 2048 Lecture_Notes def456 192.168.1.3 5000>" | nc localhost 6000
echo "<REQ LIST>" | nc localhost 6000
```

**Expected:**
```
<REP LIST 2>
<1 movie1.avi 109283519 abc123>
<2 notes.txt 2048 def456>
<REP LIST END>
```

---

## Test 6 — GET

```bash
echo "<GET movie1.avi.track>" | nc localhost 6000
```

**Expected:**
```
<REP GET BEGIN>
Filename: movie1.avi
Filesize: 109283519
Description: Ghost_and_the_Darkness
MD5: abc123
#list of peers follows next
192.168.1.1:2097:0:109283519:<timestamp>
10.0.0.2:3000:0:109283519:<timestamp>

<REP GET END <md5hash>>
```

**GET a file that does not exist:**
```bash
echo "<GET fake.track>" | nc localhost 6000
```

**Expected:**
```
<GET invalid>
```

---

## Test 7 — Multithreading

Fire three commands simultaneously from one terminal:

```bash
echo "<createtracker file1.txt 100 desc aaa111 1.1.1.1 4000>" | nc localhost 6000 &
echo "<createtracker file2.txt 200 desc bbb222 2.2.2.2 4001>" | nc localhost 6000 &
echo "<REQ LIST>" | nc localhost 6000 &
wait
```

**Expected:** all three respond without errors, server does not crash.

**Check both files were created cleanly:**
```bash
ls torrents/
cat torrents/file1.txt.track
cat torrents/file2.txt.track
```

---

## Test 8 — Two machines (midterm demo): WHAT WE NEED TO DO

On one machine (server), find IP:
```bash
ipconfig getifaddr en0
```

On other person's machine (client), replace `SERVER_IP` with above IP:
```bash
echo "<createtracker demo.mp4 500000 Demo_File abc999 192.168.1.5 7000>" | nc SERVER_IP 6000
echo "<REQ LIST>" | nc SERVER_IP 6000
echo "<GET demo.mp4.track>" | nc SERVER_IP 6000
```

**Expected:** same responses as local tests above, proving cross-machine communication works.
