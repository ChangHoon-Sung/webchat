var user_id, room_id;
var myname = get_name();

var ws = new WebSocket("ws://localhost:5500/chat");
ws.onopen = function () {
    ws.send(JSON.stringify({
        type: 'init',
        name: myname,
        room_id: 0
    }));
};
ws.onmessage = function (response) {
    //TODO: 유저 구분을 위해 ID를 받아와야하고, 이를 메세지와 구분해야분
    let res = JSON.parse(response.data);
    if (res.type == 'init') {
        user_id = res.user_id;
        room_id = res.room_id;
        document.getElementById('message').innerHTML = `${myname} (id:${user_id}) joined at ${new Date().toLocaleTimeString()} <br>`;
    }
    else if (res.type == 'msg') {
        msg_box = document.getElementById('msg_box');
        msg_box.scrollTop = msg_box.scrollHeight - msg_box.clientHeight;
        document.getElementById('message').innerHTML += `${myname}: ${res.content} <br>`;
        document.getElementById('btn_send').disabled = false;
    }
    else if (res.type == 'quit') {
        document.getElementById('message').innerHTML += `${myname} disconnected at ${new Date().toLocaleTimeString()} <br>`;
    }
};
ws.onclose = function () {
    // websocket is closed.
    document.getElementById("message").innerHTML += "Connection is closed. <br>";
    document.getElementById("input_msg").disabled = true;
    document.getElementById("btn_send").disabled = true;
    document.getElementById("btn_quit").disabled = true;
};

function get_name() {
    let name = prompt("Enter your nickname", "Anonymous");
    if (name == null || name == "") {
        name = "Anonymous";
    }
    return name;
}

function send_msg() {
    var content = document.getElementById('input_msg').value;
    if (content == "") return;

    document.getElementById('btn_send').disabled = true;
    document.getElementById('input_msg').value = "";
    ws.send(JSON.stringify({
        type: 'msg',
        room_id: room_id,
        user_id: user_id,
        content: content
    }));
}

function close_socket(){
    ws.close();
}

