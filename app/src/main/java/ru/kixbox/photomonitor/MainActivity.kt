package ru.kixbox.photomonitor

import android.app.Application
import android.content.Context
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.Refresh
import androidx.compose.material.icons.outlined.Settings
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.viewmodel.compose.viewModel
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL
import java.text.NumberFormat
import java.time.OffsetDateTime
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.util.Locale

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent { KixboxMonitorTheme { MonitorApp() } }
    }
}

data class DailyPoint(
    val date: String,
    val processed: Int,
    val ready: Int,
    val costUsd: Double
)

data class BatchRow(
    val folder: String,
    val sourceTotal: Int,
    val processed: Int,
    val ready: Int,
    val manual: Int,
    val failed: Int,
    val state: String
)

data class MonitorSnapshot(
    val generatedAt: String,
    val dataStatus: String,
    val targetTotal: Int,
    val processedSource: Int,
    val remainingSource: Int,
    val progressPercent: Double,
    val readyTotal: Int,
    val manualTotal: Int,
    val failedTotal: Int,
    val averageDailySource7d: Double,
    val averageDailyReady7d: Double,
    val estimatedDaysRemaining: Double?,
    val estimatedCompletionAt: String?,
    val currentBatch: BatchRow?,
    val daily: List<DailyPoint>,
    val batches: List<BatchRow>,
    val creditsConfigured: Boolean,
    val openingBalanceUsd: Double?,
    val topupsUsd: Double?,
    val creditsBalanceUsd: Double?,
    val costsTodayUsd: Double?,
    val costs7dUsd: Double?,
    val costsTotalUsd: Double?,
    val costPerReadyUsd: Double?,
    val projectedCostRemainingUsd: Double?,
    val creditsEnough: Boolean?
)

sealed interface ScreenState {
    data object Loading : ScreenState
    data class Ready(val snapshot: MonitorSnapshot) : ScreenState
    data class Error(val message: String) : ScreenState
}

class MonitorViewModel(application: Application) : AndroidViewModel(application) {
    private val prefs = application.getSharedPreferences("monitor", Context.MODE_PRIVATE)
    var state by mutableStateOf<ScreenState>(ScreenState.Loading)
        private set
    var endpoint by mutableStateOf(prefs.getString("endpoint", "") ?: "")
        private set
    var apiToken by mutableStateOf(prefs.getString("api_token", "") ?: "")
        private set

    init {
        refresh()
        viewModelScope.launch {
            while (true) {
                delay(60_000)
                if (endpoint.isNotBlank()) refresh(silent = true)
            }
        }
    }

    fun saveConnection(value: String, token: String) {
        endpoint = value.trim().trimEnd('/')
        apiToken = token.trim()
        prefs.edit().putString("endpoint", endpoint).putString("api_token", apiToken).apply()
        refresh()
    }

    fun refresh(silent: Boolean = false, forceServer: Boolean = false) {
        if (endpoint.isBlank()) {
            state = ScreenState.Error("Укажите адрес сервера мониторинга")
            return
        }
        val current = (state as? ScreenState.Ready)?.snapshot
        val previousGeneratedAt = current?.generatedAt
        if (!silent) {
            state = current?.let { ScreenState.Ready(it.copy(dataStatus = "updating")) }
                ?: ScreenState.Loading
        }
        viewModelScope.launch {
            state = try {
                if (forceServer) triggerServerRefresh("$endpoint/api/v1/refresh")
                var received = fetchSnapshot("$endpoint/api/v1/monitor")
                if (forceServer) {
                    var attempts = 0
                    while ((received.generatedAt == previousGeneratedAt || received.dataStatus != "live") && attempts < 72) {
                        state = ScreenState.Ready(received.copy(dataStatus = "updating"))
                        delay(5_000)
                        received = fetchSnapshot("$endpoint/api/v1/monitor")
                        attempts += 1
                    }
                    if (received.generatedAt == previousGeneratedAt || received.dataStatus != "live") {
                        received = received.copy(dataStatus = "updating")
                    }
                }
                ScreenState.Ready(received)
            } catch (e: Exception) {
                cachedSnapshot()?.let {
                    ScreenState.Ready(it.copy(dataStatus = "updating"))
                } ?: ScreenState.Error(e.message ?: "Не удалось получить данные")
            }
        }
    }

    private fun cachedSnapshot(): MonitorSnapshot? =
        prefs.getString("last_live_snapshot", null)?.let { raw ->
            runCatching { parseSnapshot(raw) }.getOrNull()
        }

    private suspend fun triggerServerRefresh(url: String) = withContext(Dispatchers.IO) {
        val connection = URL(url).openConnection() as HttpURLConnection
        connection.connectTimeout = 12_000
        connection.readTimeout = 20_000
        if (apiToken.isNotBlank()) connection.setRequestProperty("Authorization", "Bearer $apiToken")
        connection.requestMethod = "POST"
        try {
            if (connection.responseCode !in 200..299) {
                error("Сервер вернул HTTP ${connection.responseCode}")
            }
        } finally {
            connection.disconnect()
        }
    }

    private suspend fun fetchSnapshot(url: String): MonitorSnapshot = withContext(Dispatchers.IO) {
        val connection = URL(url).openConnection() as HttpURLConnection
        connection.connectTimeout = 12_000
        connection.readTimeout = 20_000
        connection.setRequestProperty("Accept", "application/json")
        if (apiToken.isNotBlank()) connection.setRequestProperty("Authorization", "Bearer $apiToken")
        connection.requestMethod = "GET"
        try {
            if (connection.responseCode !in 200..299) {
                error("Сервер вернул HTTP ${connection.responseCode}")
            }
            val raw = connection.inputStream.bufferedReader().use { it.readText() }
            val received = parseSnapshot(raw)
            if (received.dataStatus == "live") {
                prefs.edit().putString("last_live_snapshot", raw).apply()
                received
            } else {
                cachedSnapshot()?.copy(dataStatus = "updating")
                    ?: received.copy(dataStatus = "updating")
            }
        } finally {
            connection.disconnect()
        }
    }
}

private fun JSONObject.optNullableDouble(name: String): Double? =
    if (isNull(name) || !has(name)) null else optDouble(name)

private fun JSONObject.optNullableString(name: String): String? =
    if (isNull(name) || !has(name)) null else optString(name)

private fun parseBatch(value: JSONObject): BatchRow = BatchRow(
    folder = value.optString("folder"),
    sourceTotal = value.optInt("source_total"),
    processed = value.optInt("processed"),
    ready = value.optInt("ready"),
    manual = value.optInt("manual"),
    failed = value.optInt("failed"),
    state = value.optString("state")
)

private fun parseSnapshot(raw: String): MonitorSnapshot {
    val root = JSONObject(raw)
    fun JSONObject.objects(name: String): List<JSONObject> {
        val array = optJSONArray(name) ?: JSONArray()
        return (0 until array.length()).map { array.getJSONObject(it) }
    }
    val credits = root.optJSONObject("credits") ?: JSONObject()
    return MonitorSnapshot(
        generatedAt = root.optString("generated_at"),
        dataStatus = root.optString("data_status", "unknown"),
        targetTotal = root.optInt("target_total"),
        processedSource = root.optInt("processed_source"),
        remainingSource = root.optInt("remaining_source"),
        progressPercent = root.optDouble("progress_percent"),
        readyTotal = root.optInt("ready_total"),
        manualTotal = root.optInt("manual_total"),
        failedTotal = root.optInt("failed_total"),
        averageDailySource7d = root.optDouble("average_daily_source_7d"),
        averageDailyReady7d = root.optDouble("average_daily_ready_7d"),
        estimatedDaysRemaining = root.optNullableDouble("estimated_days_remaining"),
        estimatedCompletionAt = root.optNullableString("estimated_completion_at"),
        currentBatch = root.optJSONObject("current_batch")?.let(::parseBatch),
        daily = root.objects("daily").map {
            DailyPoint(it.optString("date"), it.optInt("processed"), it.optInt("ready"), it.optDouble("cost_usd"))
        },
        batches = root.objects("batches").map(::parseBatch),
        creditsConfigured = credits.optBoolean("configured", false),
        openingBalanceUsd = credits.optNullableDouble("opening_balance_usd"),
        topupsUsd = credits.optNullableDouble("topups_usd"),
        creditsBalanceUsd = credits.optNullableDouble("balance_usd"),
        costsTodayUsd = credits.optNullableDouble("costs_today_usd"),
        costs7dUsd = credits.optNullableDouble("costs_7d_usd"),
        costsTotalUsd = credits.optNullableDouble("costs_total_usd"),
        costPerReadyUsd = credits.optNullableDouble("cost_per_ready_usd"),
        projectedCostRemainingUsd = credits.optNullableDouble("projected_cost_remaining_usd"),
        creditsEnough = if (credits.isNull("enough_to_finish") || !credits.has("enough_to_finish")) null else credits.optBoolean("enough_to_finish")
    )
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun MonitorApp(vm: MonitorViewModel = viewModel()) {
    var showSettings by remember { mutableStateOf(false) }
    Scaffold(
        containerColor = AppBackground,
        topBar = {
            TopAppBar(
                title = {
                    Column {
                        Text("KIXBOX Monitor", fontWeight = FontWeight.Bold)
                        Text("Обработка фотографий", fontSize = 12.sp, color = Muted)
                    }
                },
                colors = TopAppBarDefaults.topAppBarColors(containerColor = AppBackground),
                actions = {
                    IconButton(onClick = { vm.refresh(forceServer = true) }) { Icon(Icons.Outlined.Refresh, "Обновить") }
                    IconButton(onClick = { showSettings = true }) { Icon(Icons.Outlined.Settings, "Настройки") }
                }
            )
        }
    ) { padding ->
        when (val state = vm.state) {
            ScreenState.Loading -> Box(Modifier.fillMaxSize().padding(padding), contentAlignment = Alignment.Center) { CircularProgressIndicator() }
            is ScreenState.Error -> ErrorState(state.message, Modifier.padding(padding)) { showSettings = true }
            is ScreenState.Ready -> Dashboard(state.snapshot, Modifier.padding(padding))
        }
    }
    if (showSettings) {
        EndpointDialog(vm.endpoint, vm.apiToken, onDismiss = { showSettings = false }) { endpoint, token ->
            vm.saveConnection(endpoint, token)
            showSettings = false
        }
    }
}

@Composable
private fun Dashboard(data: MonitorSnapshot, modifier: Modifier = Modifier) {
    LazyColumn(
        modifier = modifier.fillMaxSize(),
        contentPadding = PaddingValues(16.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp)
    ) {
        item { DataFreshnessStatus(data) }
        item { ProgressHero(data) }
        item {
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                MetricCard("Пройдено", intFormat(data.processedSource), "из ${intFormat(data.targetTotal)}", Modifier.weight(1f))
                MetricCard("Осталось", intFormat(data.remainingSource), "исходников", Modifier.weight(1f))
            }
        }
        item {
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                MetricCard("Скорость", intFormat(data.averageDailySource7d.toInt()), "исходников/день", Modifier.weight(1f))
                MetricCard("Готовых", intFormat(data.averageDailyReady7d.toInt()), "фото/день", Modifier.weight(1f))
            }
        }
        item { CreditsCard(data) }
        if (data.daily.isNotEmpty()) item { ThroughputCard(data.daily) }
        data.currentBatch?.let { batch -> item { CurrentBatchCard(batch) } }
        item {
            Text("Последние партии", fontWeight = FontWeight.Bold, fontSize = 18.sp)
        }
        items(data.batches.take(8)) { BatchCard(it) }
        item {
            Text(
                "Обновлено: ${formatTimestamp(data.generatedAt)}",
                color = Muted,
                fontSize = 12.sp,
                modifier = Modifier.padding(bottom = 18.dp)
            )
        }
    }
}

@Composable
private fun DataFreshnessStatus(data: MonitorSnapshot) {
    val updating = data.dataStatus != "live"
    Row(
        modifier = Modifier.fillMaxWidth().padding(horizontal = 2.dp, vertical = 1.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(7.dp)
    ) {
        if (updating) {
            CircularProgressIndicator(
                modifier = Modifier.size(12.dp),
                strokeWidth = 1.5.dp,
                color = Warning
            )
        }
        Text(
            buildString {
                append("Данные на ${formatTimestamp(data.generatedAt)}")
                if (updating) append(" · Подождите, идёт обновление")
            },
            color = if (updating) Warning else Muted,
            fontSize = 11.sp
        )
    }
}

@Composable
private fun ProgressHero(data: MonitorSnapshot) {
    val completion = data.estimatedCompletionAt?.let(::formatTimestamp) ?: "Недостаточно данных"
    val days = data.estimatedDaysRemaining?.let { String.format(Locale.US, "%.1f дня", it) } ?: "—"
    Surface(shape = RoundedCornerShape(24.dp), color = Ink, contentColor = Color.White) {
        Column(Modifier.padding(22.dp), verticalArrangement = Arrangement.spacedBy(14.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Column(Modifier.weight(1f)) {
                    Text("Общий прогресс", color = Color.White.copy(alpha = .68f), fontSize = 13.sp)
                    Text(String.format(Locale.US, "%.1f%%", data.progressPercent), fontWeight = FontWeight.Bold, fontSize = 38.sp)
                }
                Box(contentAlignment = Alignment.Center) {
                    CircularProgressIndicator(
                        progress = { (data.progressPercent / 100.0).toFloat().coerceIn(0f, 1f) },
                        modifier = Modifier.size(68.dp),
                        strokeWidth = 8.dp,
                        color = Accent,
                        trackColor = Color.White.copy(alpha = .14f),
                        strokeCap = StrokeCap.Round
                    )
                }
            }
            HorizontalDivider(color = Color.White.copy(alpha = .12f))
            Row {
                Column(Modifier.weight(1f)) {
                    Text("Расчётное завершение", color = Color.White.copy(alpha = .62f), fontSize = 12.sp)
                    Text(completion, fontWeight = FontWeight.SemiBold)
                }
                Column(horizontalAlignment = Alignment.End) {
                    Text("Осталось", color = Color.White.copy(alpha = .62f), fontSize = 12.sp)
                    Text(days, fontWeight = FontWeight.SemiBold)
                }
            }
        }
    }
}

@Composable
private fun MetricCard(title: String, value: String, subtitle: String, modifier: Modifier = Modifier) {
    Surface(modifier = modifier, shape = RoundedCornerShape(18.dp), color = Color.White) {
        Column(Modifier.padding(16.dp)) {
            Text(title, color = Muted, fontSize = 12.sp)
            Spacer(Modifier.height(6.dp))
            Text(value, fontSize = 23.sp, fontWeight = FontWeight.Bold, color = Ink)
            Text(subtitle, color = Muted, fontSize = 12.sp)
        }
    }
}

@Composable
private fun CreditsCard(data: MonitorSnapshot) {
    Surface(shape = RoundedCornerShape(20.dp), color = Color.White) {
        Column(Modifier.padding(18.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text("OpenAI API", fontWeight = FontWeight.Bold, fontSize = 18.sp, modifier = Modifier.weight(1f))
                Text(
                    if (data.creditsConfigured) usd(data.creditsBalanceUsd) else "—",
                    color = Ink,
                    fontWeight = FontWeight.Bold,
                    fontSize = 22.sp
                )
            }
            if (!data.creditsConfigured) {
                Text("Добавьте административный ключ OpenAI и сумму пополнений на сервере — появится расчётный остаток.", color = Muted, fontSize = 13.sp)
            } else {
                Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    FinanceMetric("На начало проекта", usd(data.openingBalanceUsd), Modifier.weight(1f))
                    FinanceMetric("Пополнения", usd(data.topupsUsd), Modifier.weight(1f))
                }
                Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    FinanceMetric("Общий расход", usd(data.costsTotalUsd), Modifier.weight(1f))
                    FinanceMetric("Стоимость 1 фото", usdPerPhoto(data.costPerReadyUsd), Modifier.weight(1f))
                }
                Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    FinanceMetric("Расход за 7 дней", usd(data.costs7dUsd), Modifier.weight(1f))
                    FinanceMetric("До завершения", usd(data.projectedCostRemainingUsd), Modifier.weight(1f))
                }
            }
        }
    }
}

@Composable
private fun FinanceMetric(label: String, value: String, modifier: Modifier = Modifier) {
    Column(modifier.background(AppBackground, RoundedCornerShape(14.dp)).padding(12.dp)) {
        Text(label, color = Muted, fontSize = 11.sp)
        Text(value, fontWeight = FontWeight.Bold, fontSize = 17.sp, color = Ink)
    }
}

@Composable
private fun ThroughputCard(points: List<DailyPoint>) {
    val shown = points.takeLast(7)
    val max = (shown.maxOfOrNull { it.processed } ?: 1).coerceAtLeast(1)
    Surface(shape = RoundedCornerShape(20.dp), color = Color.White) {
        Column(Modifier.padding(18.dp)) {
            Text("Динамика за 7 дней", fontWeight = FontWeight.Bold, fontSize = 18.sp)
            Text("Исходники и готовые фотографии", color = Muted, fontSize = 12.sp)
            Spacer(Modifier.height(18.dp))
            Canvas(Modifier.fillMaxWidth().height(150.dp)) {
                val groupWidth = size.width / shown.size.coerceAtLeast(1)
                shown.forEachIndexed { index, point ->
                    val x = index * groupWidth + groupWidth * .15f
                    val sourceHeight = size.height * point.processed / max
                    val readyHeight = size.height * point.ready / max
                    drawRoundRect(Accent, Offset(x, size.height - sourceHeight), Size(groupWidth * .30f, sourceHeight))
                    drawRoundRect(AccentSoft, Offset(x + groupWidth * .34f, size.height - readyHeight), Size(groupWidth * .30f, readyHeight))
                }
            }
            Row(Modifier.fillMaxWidth()) {
                shown.forEach { Text(it.date.takeLast(5), color = Muted, fontSize = 10.sp, modifier = Modifier.weight(1f)) }
            }
            Spacer(Modifier.height(10.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(16.dp)) {
                LegendDot(Accent, "Исходники")
                LegendDot(AccentSoft, "Готовые")
            }
        }
    }
}

@Composable
private fun LegendDot(color: Color, label: String) {
    Row(verticalAlignment = Alignment.CenterVertically) {
        Box(Modifier.size(8.dp).background(color, RoundedCornerShape(50)))
        Spacer(Modifier.width(6.dp))
        Text(label, color = Muted, fontSize = 12.sp)
    }
}

@Composable
private fun CurrentBatchCard(batch: BatchRow) {
    Surface(shape = RoundedCornerShape(20.dp), color = Accent.copy(alpha = .09f)) {
        Column(Modifier.padding(18.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text("Сейчас в работе", color = AccentDark, fontSize = 12.sp, fontWeight = FontWeight.Bold)
            Text(batch.folder.replace('_', '.'), color = Ink, fontSize = 22.sp, fontWeight = FontWeight.Bold)
            LinearProgressIndicator(
                progress = { if (batch.sourceTotal == 0) 0f else batch.processed.toFloat() / batch.sourceTotal },
                modifier = Modifier.fillMaxWidth().height(8.dp),
                color = Accent,
                trackColor = Accent.copy(alpha = .15f),
                strokeCap = StrokeCap.Round
            )
            Text("${intFormat(batch.processed)} из ${intFormat(batch.sourceTotal)} исходников · ${intFormat(batch.ready)} готовых", color = Muted, fontSize = 12.sp)
        }
    }
}

@Composable
private fun BatchCard(batch: BatchRow) {
    Surface(shape = RoundedCornerShape(16.dp), color = Color.White) {
        Row(Modifier.padding(15.dp), verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text(batch.folder.replace('_', '.'), fontWeight = FontWeight.SemiBold, color = Ink)
                Text("${intFormat(batch.processed)} исходников · ${intFormat(batch.ready)} готовых", color = Muted, fontSize = 12.sp)
            }
            if (batch.manual > 0 || batch.failed > 0) {
                Text("${batch.manual} / ${batch.failed}", color = if (batch.failed > 0) Danger else Warning, fontWeight = FontWeight.Bold, fontSize = 12.sp)
            } else {
                Text("Готово", color = Good, fontWeight = FontWeight.Bold, fontSize = 12.sp)
            }
        }
    }
}

@Composable
private fun ErrorState(message: String, modifier: Modifier = Modifier, onSettings: () -> Unit) {
    Box(modifier.fillMaxSize().padding(24.dp), contentAlignment = Alignment.Center) {
        Surface(shape = RoundedCornerShape(22.dp), color = Color.White) {
            Column(Modifier.padding(24.dp), horizontalAlignment = Alignment.CenterHorizontally) {
                Text("Монитор пока не подключён", fontWeight = FontWeight.Bold, fontSize = 20.sp)
                Spacer(Modifier.height(8.dp))
                Text(message, color = Muted)
                Spacer(Modifier.height(18.dp))
                Button(onClick = onSettings) { Text("Указать адрес сервера") }
            }
        }
    }
}

@Composable
private fun EndpointDialog(current: String, currentToken: String, onDismiss: () -> Unit, onSave: (String, String) -> Unit) {
    var value by remember(current) { mutableStateOf(current) }
    var token by remember(currentToken) { mutableStateOf(currentToken) }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Сервер мониторинга") },
        text = {
            Column {
                Text("Адрес API хранится только на этом телефоне.", color = Muted, fontSize = 13.sp)
                Spacer(Modifier.height(10.dp))
                OutlinedTextField(
                    value = value,
                    onValueChange = { value = it },
                    label = { Text("https://monitor.example.ru") },
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri),
                    singleLine = true
                )
                Spacer(Modifier.height(10.dp))
                OutlinedTextField(
                    value = token,
                    onValueChange = { token = it },
                    label = { Text("Токен доступа") },
                    singleLine = true
                )
            }
        },
        confirmButton = { TextButton(onClick = { onSave(value, token) }, enabled = value.isNotBlank()) { Text("Сохранить") } },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Отмена") } }
    )
}

private fun intFormat(value: Int): String = NumberFormat.getIntegerInstance(Locale("ru", "RU")).format(value)
private fun usd(value: Double?): String = value?.let { "$" + String.format(Locale.US, "%.2f", it) } ?: "—"
private fun usdPerPhoto(value: Double?): String = value?.let { "$" + String.format(Locale.US, "%.3f", it) } ?: "—"
private fun formatTimestamp(value: String): String = try {
    OffsetDateTime.parse(value)
        .atZoneSameInstant(ZoneId.systemDefault())
        .format(DateTimeFormatter.ofPattern("dd.MM.yyyy HH:mm"))
} catch (_: Exception) { value }

private val AppBackground = Color(0xFFF4F6F8)
private val Ink = Color(0xFF111827)
private val Muted = Color(0xFF6B7280)
private val Accent = Color(0xFF2563EB)
private val AccentDark = Color(0xFF1D4ED8)
private val AccentSoft = Color(0xFF93C5FD)
private val Good = Color(0xFF15803D)
private val Warning = Color(0xFFB45309)
private val Danger = Color(0xFFB91C1C)

@Composable
private fun KixboxMonitorTheme(content: @Composable () -> Unit) {
    MaterialTheme(
        colorScheme = lightColorScheme(
            primary = Accent,
            background = AppBackground,
            surface = Color.White,
            onSurface = Ink
        ),
        content = content
    )
}
