package ru.kixbox.photomonitor

import android.app.Application
import android.content.Context
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.viewmodel.compose.viewModel
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL
import java.text.NumberFormat
import java.time.OffsetDateTime
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.util.Locale

private val RInk = Color(0xFF152F35)
private val RGreen = Color(0xFF75DBB0)
private val RDarkGreen = Color(0xFF217957)
private val RMuted = Color(0xFF75858A)
private val RTrack = Color(0xFFE6EDEE)
private val RAmber = Color(0xFFE6AA42)
private fun rn(v:Int)=NumberFormat.getIntegerInstance(Locale("ru")).format(v)
private fun rp(v:Double)=String.format(Locale("ru"), "%.1f%%",v)
private fun rt(v:String)=runCatching { OffsetDateTime.parse(v).atZoneSameInstant(ZoneId.of("Europe/Moscow")).format(DateTimeFormatter.ofPattern("dd.MM HH:mm"))+" МСК" }.getOrDefault("—")
private fun folderLabel(v:String)=runCatching { java.time.LocalDate.parse(v.replace('_','-')).format(DateTimeFormatter.ofPattern("d MMMM",Locale("ru"))) }.getOrDefault(v)
private fun phaseLabel(v:String)=when(v){
    "paused"->"На паузе";"reviewing"->"Разбор бирок";"matching"->"Сверка с ассортиментом";"renaming"->"Переименование";"verifying"->"Проверка результата";"error"->"Требуется внимание";"awaiting_update"->"Ждём обновления статуса";else->"Нет активной работы"
}
data class RenameFolder(val id:String,val name:String,val total:Int,val renamed:Int,val remaining:Int,val review:Int,val percent:Double,val state:String)
data class RenameData(val at:String,val status:String,val total:Int,val renamed:Int,val remaining:Int,val review:Int,val percent:Double,val complete:Int,val folders:List<RenameFolder>,val phase:String,val folder:String,val message:String,val workAt:String,val hours:Double?,val eta:String?,val forecast:String,val error:String?)
private fun renameData(raw:String):RenameData {
    val j=JSONObject(raw);val a=j.getJSONArray("folders");val w=j.optJSONObject("work")?:JSONObject()
    val rows=(0 until a.length()).map { i-> val r=a.getJSONObject(i);RenameFolder(r.getString("id"),r.getString("name"),r.getInt("total"),r.getInt("renamed"),r.getInt("remaining"),r.optInt("review"),r.optDouble("progress_percent"),r.optString("state")) }
    return RenameData(j.getString("generated_at"),j.optString("data_status"),j.getInt("total"),j.getInt("renamed"),j.getInt("remaining"),j.optInt("review"),j.getDouble("progress_percent"),j.optInt("folders_complete"),rows,w.optString("phase","paused"),w.optString("folder_name").takeUnless{it=="null"}?:"",w.optString("message"),w.optString("updated_at"),if(j.isNull("estimated_hours_remaining"))null else j.optDouble("estimated_hours_remaining"),j.optString("estimated_completion_at").takeUnless{it=="null"||it.isBlank()},j.optString("forecast_note"),j.optString("refresh_error").takeUnless{it=="null"||it.isBlank()})
}
class RenameViewModel(application:Application):AndroidViewModel(application){
    private val prefs=application.getSharedPreferences("rename_monitor",Context.MODE_PRIVATE)
    var data by mutableStateOf<RenameData?>(null);private set
    var loading by mutableStateOf(false);private set
    var error by mutableStateOf<String?>(null);private set
    private var connectionKey=""
    fun refresh(endpoint:String,token:String){
        if(endpoint.isBlank()){error="Укажите адрес сервера в настройках";return}
        val key=endpoint+"|"+token.hashCode()
        if(connectionKey!=key){connectionKey=key;data=null;error=null}
        if(loading)return
        loading=true
        viewModelScope.launch {
            try {
                val raw=withContext(Dispatchers.IO){
                    val c=URL("${endpoint.trimEnd('/')}/api/v1/rename-monitor").openConnection() as HttpURLConnection
                    c.connectTimeout=12000;c.readTimeout=20000;c.setRequestProperty("Authorization","Bearer $token")
                    try {if(c.responseCode==503)error("Идёт первичная инвентаризация. Данные появятся автоматически.")
                        if(c.responseCode !in 200..299)error("Не удалось обновить данные: HTTP ${c.responseCode}")
                        c.inputStream.bufferedReader().use{it.readText()}
                    }finally{c.disconnect()}
                }
                if(connectionKey==key){data=renameData(raw);error=null;prefs.edit().putString("key",key).putString("snapshot",raw).apply()}
            }catch(e:Exception){
                if(connectionKey==key){
                    if(data==null&&prefs.getString("key",null)==key)data=runCatching{renameData(prefs.getString("snapshot",null)!!)}.getOrNull()
                    data=data?.copy(status="offline");error=e.message?:"Нет связи с сервером"
                }
            }finally{loading=false}
        }
    }
}

@Composable
fun RenameScreen(endpoint:String,token:String,refreshTick:Int,modifier:Modifier=Modifier,vm:RenameViewModel=viewModel()){
    LaunchedEffect(endpoint,token,refreshTick){
        while(true){vm.refresh(endpoint,token);delay(30_000)}
    }
    val d=vm.data
    if(d==null){Box(modifier.fillMaxSize().padding(28.dp),contentAlignment=Alignment.Center){Column(horizontalAlignment=Alignment.CenterHorizontally,verticalArrangement=Arrangement.spacedBy(16.dp)){if(vm.loading)CircularProgressIndicator(color=RDarkGreen);Text(vm.error?:"Считаем фотографии по папкам…",color=RMuted);TextButton(onClick={vm.refresh(endpoint,token)}){Text("Обновить")}}};return}
    var filter by remember {mutableStateOf("Все")}
    val shown=d.folders.filter {when(filter){"Остались"->it.remaining>0;"Завершены"->it.total>0&&it.remaining==0;else->true}}
    LazyColumn(modifier.fillMaxSize(),contentPadding=PaddingValues(16.dp),verticalArrangement=Arrangement.spacedBy(14.dp)){
        item{Text("Данные на ${rt(d.at)}"+if(vm.loading)" · обновляем" else "",fontSize=11.sp,color=RMuted)}
        if(vm.error!=null||d.error!=null||d.status!="live")item{Surface(color=Color(0xFFFFF2D9),shape=RoundedCornerShape(14.dp)){Text(vm.error?:d.error?:"Данные устарели — показан последний сохранённый результат",Modifier.padding(14.dp),fontSize=12.sp,color=RInk)}}
        item{RenameHero(d)}
        item{Row(horizontalArrangement=Arrangement.spacedBy(10.dp)){RenameMetric("Переименовано",rn(d.renamed),"фотографий",Modifier.weight(1f),RDarkGreen);RenameMetric("Осталось",rn(d.remaining),"фотографий",Modifier.weight(1f),RInk)}}
        item{Surface(color=Color.White,shape=RoundedCornerShape(18.dp)){Column(Modifier.fillMaxWidth().padding(18.dp),verticalArrangement=Arrangement.spacedBy(8.dp)){
            Text(phaseLabel(d.phase),color=if(d.phase=="error")RAmber else RDarkGreen,fontWeight=FontWeight.Bold)
            Text(if(d.folder.isBlank())"Папка не назначена" else folderLabel(d.folder),fontSize=22.sp,fontWeight=FontWeight.Bold,color=RInk)
            if(d.message.isNotBlank())Text(d.message,fontSize=13.sp,color=RMuted)
            if(d.workAt.isNotBlank())Text("Статус на ${rt(d.workAt)}",fontSize=11.sp,color=RMuted)
        }}}
        item{RenameForecast(d)}
        item{FolderChart(d.folders)}
        item{Row(Modifier.fillMaxWidth(),horizontalArrangement=Arrangement.SpaceBetween){Text("Все папки",fontSize=20.sp,fontWeight=FontWeight.Bold,color=RInk);Text("${d.complete} / ${d.folders.size} завершены",color=RMuted,fontSize=12.sp)}}
        item{Row(horizontalArrangement=Arrangement.spacedBy(8.dp)){listOf("Все","Остались","Завершены").forEach{label->FilterChip(selected=filter==label,onClick={filter=label},label={Text(label)})}}}
        items(shown,key={it.id}){RenameFolderCard(it)}
        if(shown.isEmpty())item{Text("Таких папок пока нет",color=RMuted)}
        item{Text("Считаем фотографии во всех папках «02 готово». Переименованные — в подпапках «Переименовано». Отчёты и служебные файлы исключены. Новые результаты ретуши увеличивают общий план.",fontSize=11.sp,color=RMuted,modifier=Modifier.padding(bottom=24.dp))}
    }
}
@Composable
private fun RenameHero(d:RenameData){Surface(color=RInk,contentColor=Color.White,shape=RoundedCornerShape(24.dp)){Column(Modifier.fillMaxWidth().padding(22.dp),verticalArrangement=Arrangement.spacedBy(14.dp)){
    Text("ПЕРЕИМЕНОВАНИЕ · 02 ГОТОВО",fontSize=11.sp,color=Color.White.copy(alpha=.65f),letterSpacing=1.sp)
    Row(verticalAlignment=Alignment.CenterVertically){Column(Modifier.weight(1f)){Text(rp(d.percent),fontSize=44.sp,fontWeight=FontWeight.Bold);Text("${rn(d.renamed)} из ${rn(d.total)} фото",fontSize=14.sp,color=Color.White.copy(alpha=.8f))};CircularProgressIndicator(progress={(d.percent/100).toFloat().coerceIn(0f,1f)},modifier=Modifier.size(76.dp),color=RGreen,trackColor=Color.White.copy(alpha=.12f),strokeWidth=8.dp,strokeCap=StrokeCap.Round)}
    HorizontalDivider(color=Color.White.copy(alpha=.12f))
    Text("Цель — ${rn(d.total)} переименованных фотографий",fontWeight=FontWeight.SemiBold,fontSize=14.sp)
    Text("${rn(d.review)} отмечены для ручного решения · входят в остаток",fontSize=12.sp,color=Color.White.copy(alpha=.65f))
}}}
@Composable
private fun RenameMetric(label:String,value:String,unit:String,modifier:Modifier,color:Color){Surface(modifier,color=Color.White,shape=RoundedCornerShape(18.dp)){Column(Modifier.padding(16.dp)){Text(label,color=RMuted,fontSize=12.sp);Text(value,color=color,fontSize=28.sp,fontWeight=FontWeight.Bold);Text(unit,color=RMuted,fontSize=12.sp)}}}
@Composable
private fun RenameForecast(d:RenameData){Surface(color=Color.White,shape=RoundedCornerShape(18.dp)){Column(Modifier.fillMaxWidth().padding(18.dp),verticalArrangement=Arrangement.spacedBy(8.dp)){
    Text("Прогноз завершения",fontWeight=FontWeight.Bold,color=RInk,fontSize=17.sp)
    Text(d.eta?.let{rt(it)}?:if(d.phase=="paused")"После возобновления" else "Набираем статистику",fontSize=21.sp,fontWeight=FontWeight.SemiBold,color=RInk)
    d.hours?.let{Text("Ориентировочно ещё ${String.format(Locale("ru"),"%.1f",it)} ч при наблюдаемом темпе",color=RDarkGreen,fontSize=13.sp)}
    Text(d.forecast,fontSize=12.sp,color=RMuted)
}}}
@Composable
private fun FolderChart(rows:List<RenameFolder>){var selected by remember{mutableStateOf<String?>(null)};val max=(rows.maxOfOrNull{it.total}?:1).coerceAtLeast(1)
    Surface(color=Color.White,shape=RoundedCornerShape(20.dp)){Column(Modifier.fillMaxWidth().padding(18.dp),verticalArrangement=Arrangement.spacedBy(10.dp)){
        Text("Динамика по папкам",fontWeight=FontWeight.Bold,fontSize=18.sp,color=RInk)
        Text("Зелёный — переименовано · серый — осталось",fontSize=11.sp,color=RMuted)
        val item=rows.find{it.id==selected}
        Text(item?.let{"${folderLabel(it.name)}: ${rn(it.renamed)} / ${rn(it.total)} · ${rp(it.percent)}"}?:"Листайте график и нажимайте на столбцы",fontSize=12.sp,color=RDarkGreen)
        Row(Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()),horizontalArrangement=Arrangement.spacedBy(10.dp),verticalAlignment=Alignment.Bottom){rows.forEach{f->
            Column(Modifier.width(52.dp).clickable{selected=f.id},horizontalAlignment=Alignment.CenterHorizontally){
                Text(rp(f.percent),fontSize=10.sp,color=if(selected==f.id)RDarkGreen else RMuted)
                Box(Modifier.height(130.dp).fillMaxWidth(),contentAlignment=Alignment.BottomCenter){
                    Column(Modifier.width(30.dp).height((120f*f.total/max).coerceAtLeast(3f).dp).background(RTrack,RoundedCornerShape(topStart=5.dp,topEnd=5.dp)),verticalArrangement=Arrangement.Bottom){
                        if(f.renamed>0)Box(Modifier.fillMaxWidth().height((120f*f.renamed/max).dp).background(RGreen))
                    }
                }
                Text(if(Regex("\\d{4}_\\d{2}_\\d{2}").matches(f.name))f.name.takeLast(2)+"."+f.name.substring(5,7) else f.name.take(8),fontSize=10.sp,color=RInk,maxLines=1,modifier=Modifier.padding(top=6.dp))
            }
        }}
    }}
}
@Composable
private fun RenameFolderCard(f:RenameFolder){Surface(color=Color.White,shape=RoundedCornerShape(18.dp)){Column(Modifier.fillMaxWidth().padding(16.dp),verticalArrangement=Arrangement.spacedBy(10.dp)){
    Row(verticalAlignment=Alignment.CenterVertically){Column(Modifier.weight(1f)){Text(folderLabel(f.name),fontWeight=FontWeight.Bold,fontSize=17.sp,color=RInk);Text(when(f.state){"completed"->"Завершена";"working"->"Сейчас в работе";"needs_review"->"Осталось ручное решение";"empty"->"Нет фотографий";else->"Осталось ${rn(f.remaining)} фото"},fontSize=12.sp,color=if(f.state=="completed"||f.state=="working")RDarkGreen else RMuted)};Text(rp(f.percent),fontWeight=FontWeight.Bold,color=RInk)}
    LinearProgressIndicator(progress={(f.percent/100).toFloat().coerceIn(0f,1f)},modifier=Modifier.fillMaxWidth().height(6.dp),color=RGreen,trackColor=RTrack,strokeCap=StrokeCap.Round)
    Row(Modifier.fillMaxWidth(),horizontalArrangement=Arrangement.SpaceBetween){Text("${rn(f.renamed)} из ${rn(f.total)} переименовано",fontSize=12.sp,color=RMuted);if(f.review>0)Text("${f.review} проверить",fontSize=12.sp,color=RDarkGreen)}
}}}
