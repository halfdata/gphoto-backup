"use strict";

function init_paginator(base_url) {
    var inputs = document.getElementsByClassName('paginator-current-page');
    for (var i=0; i<inputs.length; i++) {
        inputs[i].addEventListener("keyup", (event) => {
            var input = event.target || event.srcElement;
            var max_value = parseInt(input.getAttribute('max-value'));
            var value_str = input.value;
            if (isNaN(value_str) || isNaN(parseInt(value_str)) && value_str != '') {
                input.value = 1;
                return;
            }
            var value = parseInt(value_str)
            if (value < 1) {
                value = 1;
                input.value = 1;
            } else if (value > max_value) {
                value = max_value;
                input.value = max_value;
            }
            if (event.keyCode == 10 || event.keyCode == 13) {
                window.location.href = base_url + "/" + value;
            }
        });
    }
}

function resize_thumbnails(event) {
    var groups = document.getElementsByClassName('images-container');
    var default_height = 160;
    var container_width = parseInt(document.getElementsByClassName('mediaitems-container')[0].offsetWidth) - 2;
    for (var i=0; i<groups.length; i++) {
        var images = groups[i].getElementsByClassName('image-container');
        var start = 0;
        var total_width = 0;
        var new_height = default_height;
        for (var j=0; j<images.length; j++) {
            var ratio = images[j].getAttribute('data-ratio');
            if (total_width + default_height*ratio + (j - start + 1) * 2 <= container_width) {
                total_width += default_height*ratio;
            } else {
                new_height = default_height * (container_width - (j - start) * 2) / total_width;
                for (var k=start; k<j; k++) {
                    images[k].style.height = new_height.toString() + 'px';
                }
                start = j;
                total_width = default_height*ratio;
            }
        }
        var last_height = default_height * (container_width - (j - start) * 2) / total_width;
        if (new_height * 1.1 > last_height) {
            new_height = last_height
        }
        for (var k=start; k<j; k++) {
            images[k].style.height = new_height.toString() + 'px';
        }
    }
}
