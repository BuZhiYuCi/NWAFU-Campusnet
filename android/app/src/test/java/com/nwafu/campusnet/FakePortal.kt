package com.nwafu.campusnet

import java.io.BufferedReader
import java.io.InputStreamReader
import java.io.OutputStream
import java.net.InetAddress
import java.net.ServerSocket
import java.net.Socket
import java.net.URLDecoder
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.CopyOnWriteArrayList

/**
 * 本地门户桩：在 127.0.0.1 的随机端口上模拟深澜门户。
 *
 * 用 [ServerSocket] 手写而不是 `com.sun.net.httpserver`，原因是后者在
 * Android 单元测试的 classpath 下可能取不到（jdk.httpserver 模块）。
 * 协议层测试**绝不**向真实校园网发请求，这一点与桌面版一致。
 */
class FakePortal {

    data class Route(
        val body: String,
        val status: Int = 200,
        val contentType: String = "application/javascript; charset=utf-8"
    )

    data class Recorded(val path: String, val query: String, val params: Map<String, String>)

    private val socket = ServerSocket(0, 50, InetAddress.getByName("127.0.0.1"))
    private var thread: Thread? = null
    @Volatile private var running = false

    val port: Int get() = socket.localPort
    val baseUrl: String get() = "http://127.0.0.1:$port"

    private val routes = ConcurrentHashMap<String, Route>()
    val requests = CopyOnWriteArrayList<Recorded>()

    fun start(): FakePortal {
        running = true
        thread = Thread({
            while (running && !socket.isClosed) {
                try {
                    socket.accept().use { handle(it) }
                } catch (e: Exception) {
                    if (running) continue else break
                }
            }
        }, "fake-portal").apply {
            isDaemon = true
            start()
        }
        return this
    }

    fun stop() {
        running = false
        try {
            socket.close()
        } catch (e: Exception) {
            // ignore
        }
    }

    fun route(path: String, body: String, status: Int = 200, contentType: String = "application/javascript; charset=utf-8") {
        routes[path] = Route(body, status, contentType)
    }

    fun jsonp(path: String, json: String, status: Int = 200) {
        route(path, "cb($json)", status)
    }

    fun json(path: String, json: String, status: Int = 200) {
        route(path, json, status, "application/json; charset=utf-8")
    }

    fun html(path: String, status: Int = 200) {
        route(path, "<html><body>portal login</body></html>", status, "text/html; charset=utf-8")
    }

    fun reset() {
        routes.clear()
        requests.clear()
    }

    fun hits(path: String): Int = requests.count { it.path == path }

    private fun handle(client: Socket) {
        val input = BufferedReader(InputStreamReader(client.getInputStream(), Charsets.ISO_8859_1))
        val requestLine = input.readLine() ?: return
        // 读完请求头
        while (true) {
            val line = input.readLine() ?: break
            if (line.isEmpty()) break
        }
        val parts = requestLine.split(" ")
        if (parts.size < 2) return
        val target = parts[1]
        val path = target.substringBefore('?')
        val query = target.substringAfter('?', "")
        val params = parseQuery(query)
        requests.add(Recorded(path, query, params))

        val route = routes[path]
        val out: OutputStream = client.getOutputStream()
        if (route == null) {
            writeResponse(out, 404, "text/plain; charset=utf-8", "not found")
        } else {
            writeResponse(out, route.status, route.contentType, route.body)
        }
        out.flush()
    }

    private fun writeResponse(out: OutputStream, status: Int, contentType: String, body: String) {
        val bytes = body.toByteArray(Charsets.UTF_8)
        val head = buildString {
            append("HTTP/1.1 ").append(status).append(' ')
            append(if (status == 200) "OK" else "ERR").append("\r\n")
            append("Content-Type: ").append(contentType).append("\r\n")
            append("Content-Length: ").append(bytes.size).append("\r\n")
            append("Connection: close\r\n\r\n")
        }
        out.write(head.toByteArray(Charsets.ISO_8859_1))
        out.write(bytes)
    }

    private fun parseQuery(query: String): Map<String, String> {
        if (query.isEmpty()) return emptyMap()
        return query.split("&").mapNotNull { pair ->
            if (pair.isEmpty()) return@mapNotNull null
            val k = pair.substringBefore('=')
            val v = pair.substringAfter('=', "")
            decode(k) to decode(v)
        }.toMap()
    }

    private fun decode(s: String): String = try {
        URLDecoder.decode(s, "UTF-8")
    } catch (e: Exception) {
        s
    }
}
